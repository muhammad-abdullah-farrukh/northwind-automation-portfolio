"""Invoice extraction pipeline (brief §4.3):

text layer -> schema-constrained LLM extraction -> validation -> one repair pass -> confidence
-> status -> duplicate check. Shared by /v1/extract/sync now and the Celery jobs in P4.
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from statistics import mean
from typing import Any

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.core.ids import new_job_id
from app.models.db import Job
from app.models.invoice import (
    CRITICAL_FIELDS,
    INVOICE_FIELDS,
    Confidence,
    ExtractMeta,
    ExtractResponse,
    FieldConfidence,
    InvoiceData,
    LLMInvoiceOutput,
    Validation,
    ValidationIssue,
)
from app.services import dedupe, pdf_text, repair, validate
from app.services.enrich import load_prompt
from app.services.llm import LLMClient, LLMError, LLMResult, inline_refs

log = logging.getLogger(__name__)

PROMPT_VERSION = "invoice_extract_v2"  # v2 beat v1 on held-out invoices 21-40 (DECISIONS D22)
MIN_TEXT_CHARS = 50
TOOL_NAME = "record_invoice"


@dataclass
class ExtractionOutcome:
    status: str
    data: InvoiceData | None
    confidence: Confidence
    validation: Validation
    meta: ExtractMeta
    extra: dict[str, Any] = field(default_factory=dict)  # stored with the job, not part of the API contract


def _parse_and_validate(raw: dict[str, Any], today: date | None) -> tuple[LLMInvoiceOutput | None, list[ValidationIssue]]:
    try:
        out = LLMInvoiceOutput.model_validate(raw)
    except ValidationError as exc:
        issues = [
            ValidationIssue(field=".".join(str(p) for p in err["loc"]) or "document", code="schema_error", message=err["msg"])
            for err in exc.errors()[:10]
        ]
        return None, issues
    return out, validate.validate_invoice(out, today=today)


def _r2(value: float) -> float:
    """Half-up to 2 dp (plain round() turns 0.975 into 0.97 because of binary floats)."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _top_field(path: str) -> str:
    return re.split(r"[.\[]", path, maxsplit=1)[0]


SELF_REPORT_WEIGHT = 0.25  # small local models' self-reports are poorly calibrated (DECISIONS D19)
GROUNDING_WEIGHT = 0.75


def score_confidence(llm_conf: FieldConfidence, grounded: dict[str, float], errors: list[ValidationIssue]) -> Confidence:
    """Per field: mostly deterministic grounding, a quarter the model's own confidence; capped at 0.5 when a
    check names the field. A grounded, validation-clean field can't fall below 0.75 on self-report alone, while
    an ungrounded one can't rise above 0.25. Overall: half the mean, half the weakest critical field, so one
    bad total is enough to send the invoice to review."""
    flagged = {_top_field(e.field) for e in errors}
    fields: dict[str, float] = {}
    for name in INVOICE_FIELDS:
        score = SELF_REPORT_WEIGHT * getattr(llm_conf, name) + GROUNDING_WEIGHT * grounded[name]
        if name in flagged:
            score = min(score, 0.5)
        fields[name] = _r2(score)
    overall = 0.5 * mean(fields.values()) + 0.5 * min(fields[f] for f in CRITICAL_FIELDS)
    return Confidence(overall=_r2(overall), fields=fields)


def _meta(calls: list[LLMResult], model: str | None, prompt_version: str = PROMPT_VERSION) -> ExtractMeta:
    costs = [c.cost_usd for c in calls]
    return ExtractMeta(
        model=calls[-1].model if calls else model,
        prompt_version=prompt_version,
        tokens=sum(c.input_tokens + c.output_tokens for c in calls),
        cost_usd=round(sum(costs), 6) if costs and all(c is not None for c in costs) else None,
        latency_ms=sum(c.latency_ms for c in calls),
    )


async def extract_invoice(
    text: str, *, llm: LLMClient, settings: Settings, today: date | None = None, prompt_version: str = PROMPT_VERSION
) -> ExtractionOutcome:
    """Raises LLMError only when the *first* LLM call fails (nothing to show the caller yet).
    prompt_version lets the eval harness compare prompts; the API always uses PROMPT_VERSION."""
    if len(text.strip()) < MIN_TEXT_CHARS:
        issue = ValidationIssue(field="document", code="no_text_layer", message="the PDF has no text layer (scanned image?); OCR is not available")
        return ExtractionOutcome(
            status="failed",
            data=None,
            confidence=Confidence(overall=0.0),
            validation=Validation(ok=False, errors=[issue]),
            meta=_meta([], settings.llm_model_extract, prompt_version),
            extra={"text_chars": len(text.strip())},
        )

    system = load_prompt(settings.prompts_dir, prompt_version)
    user = f"<invoice_text>\n{text}\n</invoice_text>"
    schema = inline_refs(LLMInvoiceOutput.model_json_schema())
    call = dict(system=system, schema=schema, tool_name=TOOL_NAME, model=settings.llm_model_extract, max_tokens=4096, timeout=settings.llm_extract_timeout_s)

    calls = [await llm.complete_json(user=user, **call)]
    out, errors = _parse_and_validate(calls[0].data, today)
    extra: dict[str, Any] = {"repair_attempted": False, "text_chars": len(text)}

    if errors:
        extra["repair_attempted"] = True
        extra["errors_before_repair"] = [e.model_dump() for e in errors]
        template = load_prompt(settings.prompts_dir, repair.REPAIR_PROMPT_VERSION)
        message = repair.build_repair_message(template, invoice_text=text, previous=calls[0].data, errors=errors)
        try:
            calls.append(await llm.complete_json(user=message, **call))
            out2, errors2 = _parse_and_validate(calls[1].data, today)
            if out2 is not None or out is None:
                out, errors = out2, errors2
        except LLMError as exc:
            extra["repair_error"] = str(exc)
            log.warning("repair call failed", extra={"error": str(exc), "detail": exc.detail})

    meta = _meta(calls, settings.llm_model_extract, prompt_version)
    if out is None:
        return ExtractionOutcome("failed", None, Confidence(overall=0.0), Validation(ok=False, errors=errors), meta, extra)

    data = InvoiceData.model_validate(out.model_dump(exclude={"field_confidence"}))
    grounded = validate.grounding(data, text)
    confidence = score_confidence(out.field_confidence, grounded, errors)
    extra["grounding"] = grounded
    job_status = "needs_review" if errors or confidence.overall < settings.review_threshold else "done"
    return ExtractionOutcome(job_status, data, confidence, Validation(ok=not errors, errors=errors), meta, extra)


def apply_outcome(job: Job, outcome: ExtractionOutcome, *, pages: int | None) -> None:
    """Write an extraction outcome onto a job row (sync endpoint and async worker share this)."""
    job.status = outcome.status
    job.pages = pages
    job.data = outcome.data.model_dump(mode="json") if outcome.data else None
    job.confidence = outcome.confidence.model_dump()
    job.validation = outcome.validation.model_dump()
    job.meta = {**outcome.meta.model_dump(), **outcome.extra}
    job.dedupe_hash = dedupe.dedupe_hash(outcome.data) if outcome.data is not None else None


def failed_outcome(code: str, message: str, settings: Settings) -> ExtractionOutcome:
    """A terminal failure with nothing extracted (unreadable PDF, LLM unavailable after all retries)."""
    issue = ValidationIssue(field="document", code=code, message=message)
    return ExtractionOutcome("failed", None, Confidence(overall=0.0), Validation(ok=False, errors=[issue]), _meta([], settings.llm_model_extract), {})


def job_to_response(job: Job) -> ExtractResponse:
    """The brief §4.4 contract for any stored job, including queued/processing ones (no data yet)."""
    meta = job.meta or {}
    return ExtractResponse(
        job_id=job.id,
        status=job.status,
        duplicate_of=job.duplicate_of,
        data=InvoiceData.model_validate(job.data) if job.data else None,
        confidence=Confidence.model_validate(job.confidence) if job.confidence else Confidence(overall=0.0),
        validation=Validation.model_validate(job.validation) if job.validation else Validation(ok=False, errors=[]),
        meta=ExtractMeta(
            model=meta.get("model"),
            prompt_version=meta.get("prompt_version", PROMPT_VERSION),
            tokens=meta.get("tokens", 0),
            cost_usd=meta.get("cost_usd"),
            latency_ms=meta.get("latency_ms", 0),
        ),
    )


async def process_document(
    session: AsyncSession,
    *,
    api_key_id: int,
    content: bytes,
    filename: str | None,
    llm: LLMClient,
    settings: Settings,
    mode: str = "sync",
) -> ExtractResponse:
    kind = pdf_text.detect_type(content)
    if kind != "application/pdf":
        hint = " (images need OCR, which is not available yet)" if kind.startswith("image/") else ""
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"expected a PDF, got {kind}{hint}")
    try:
        doc = await run_in_threadpool(pdf_text.read_pdf_text, content, settings.extract_max_pages_sync)
    except pdf_text.DocumentError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc

    try:
        outcome = await extract_invoice(doc.text, llm=llm, settings=settings)
    except LLMError as exc:
        log.warning("extraction llm call failed", extra={"error": str(exc), "detail": exc.detail})
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"extraction unavailable: {exc}", headers={"Retry-After": "30"}
        ) from exc

    job = Job(
        id=new_job_id(),
        api_key_id=api_key_id,
        mode=mode,
        schema_name="invoice",
        file_sha256=hashlib.sha256(content).hexdigest(),
        filename=(filename or "")[:255] or None,
    )
    apply_outcome(job, outcome, pages=doc.pages)
    if job.dedupe_hash:
        job.duplicate_of = await dedupe.find_duplicate(session, job.dedupe_hash, api_key_id=api_key_id)
    session.add(job)
    await session.commit()

    log.info(
        "document extracted",
        extra={
            "job_id": job.id,
            "status": job.status,
            "duplicate_of": job.duplicate_of,
            "confidence": outcome.confidence.overall,
            "errors": len(outcome.validation.errors),
            "repair_attempted": outcome.extra.get("repair_attempted"),
            "tokens": outcome.meta.tokens,
            "llm_latency_ms": outcome.meta.latency_ms,
        },
    )
    return ExtractResponse(
        job_id=job.id,
        status=outcome.status,
        duplicate_of=job.duplicate_of,
        data=outcome.data,
        confidence=outcome.confidence,
        validation=outcome.validation,
        meta=outcome.meta,
    )
