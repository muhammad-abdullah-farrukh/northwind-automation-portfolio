"""Async extraction jobs (brief §4.3). Everything is scoped to the calling API key."""

import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.auth import require_api_key
from app.core.config import Settings, get_settings
from app.core.deps import get_session
from app.core.ids import new_job_id
from app.core.idempotency import run_idempotent
from app.models.db import ApiKey, Job, JobFile, JobReview
from app.models.invoice import ExtractResponse, JobCreated, JobStatus, JobSummary, ReviewRequest, ReviewResult, Validation
from app.models.schemas import ErrorBody
from app.services import callbacks, export, pdf_text, validate
from app.services.extract import job_to_response
from app.workers import tasks

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])
REVIEWABLE = ("done", "needs_review", "reviewed")


async def _own_job(session: AsyncSession, job_id: str, api_key: ApiKey) -> Job:
    job = await session.get(Job, job_id)
    if job is None or job.api_key_id != api_key.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")  # same answer for other clients' jobs
    return job


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobCreated,
    summary="Queue an invoice PDF for async extraction; the result is POSTed (signed) to callback_url",
    responses={409: {"model": ErrorBody}, 413: {"model": ErrorBody}, 415: {"model": ErrorBody}, 422: {"model": ErrorBody}},
)
async def create_job(
    response: Response,
    file: UploadFile = File(...),
    schema_name: str = Form("invoice", alias="schema"),
    callback_url: str | None = Form(None),
    api_key: ApiKey = Depends(require_api_key),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    if schema_name != "invoice":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unsupported schema; available: ['invoice']")
    content = await file.read(settings.upload_max_bytes + 1)
    if len(content) > settings.upload_max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"file exceeds {settings.upload_max_bytes} bytes")
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "empty file")
    kind = pdf_text.detect_type(content)
    if kind != "application/pdf":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"expected a PDF, got {kind}")
    if callback_url:
        try:
            await run_in_threadpool(callbacks.check_callback_url, callback_url, settings)  # fail fast, before queueing
        except callbacks.CallbackBlocked as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"callback_url not allowed: {exc}") from exc

    sha = hashlib.sha256(content).hexdigest()

    async def handler() -> tuple[int, dict]:
        job = Job(
            id=new_job_id(), api_key_id=api_key.id, mode="async", schema_name="invoice", status="queued",
            file_sha256=sha, filename=(file.filename or "")[:255] or None, callback_url=callback_url,
        )  # fmt: skip
        session.add(job)
        session.add(JobFile(job_id=job.id, content=content, size_bytes=len(content)))
        await session.commit()
        tasks.enqueue_job(job.id)  # only after commit, so the worker always finds the row
        return 202, JobCreated(job_id=job.id, status="queued").model_dump()

    # Without an Idempotency-Key the file's SHA-256 is the key: re-sending the same PDF returns the same job.
    result = await run_idempotent(
        session,
        api_key_id=api_key.id,
        endpoint="POST /v1/jobs",
        idem_key=idempotency_key or f"sha256:{sha}",
        body={"file_sha256": sha, "schema": schema_name, "callback_url": callback_url},
        handler=handler,
    )
    if result.status_code == 202:
        job_id = JobCreated.model_validate_json(result.body).job_id
        result.headers["Location"] = f"/v1/jobs/{job_id}"
    return result


@router.get("", response_model=list[JobSummary], summary="List jobs, newest first (e.g. ?status=needs_review)")
async def list_jobs(
    status_filter: JobStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    api_key: ApiKey = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
) -> list[JobSummary]:
    stmt = select(Job).where(Job.api_key_id == api_key.id)
    if status_filter:
        stmt = stmt.where(Job.status == status_filter)
    jobs = (await session.scalars(stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit))).all()
    return [
        JobSummary(
            job_id=j.id, status=j.status, created_at=j.created_at, filename=j.filename,
            vendor=(j.data or {}).get("vendor"), invoice_no=(j.data or {}).get("invoice_no"),
            total=(j.data or {}).get("total"), currency=(j.data or {}).get("currency"),
            confidence=(j.confidence or {}).get("overall"), duplicate_of=j.duplicate_of,
        )  # fmt: skip
        for j in jobs
    ]


@router.get("/{job_id}", response_model=ExtractResponse, summary="Job status and result (brief §4.4 contract)")
async def get_job(job_id: str, api_key: ApiKey = Depends(require_api_key), session: AsyncSession = Depends(get_session)) -> ExtractResponse:
    return job_to_response(await _own_job(session, job_id, api_key))


@router.get("/{job_id}/export", summary="Spreadsheet export of an extracted invoice", responses={409: {"model": ErrorBody}})
async def export_job(
    job_id: str,
    fmt: Literal["csv", "xlsx"] = Query(default="csv", alias="format"),
    api_key: ApiKey = Depends(require_api_key),
    session: AsyncSession = Depends(get_session),
) -> Response:
    job = await _own_job(session, job_id, api_key)
    if not job.data:
        raise HTTPException(status.HTTP_409_CONFLICT, f"job is {job.status}; nothing to export yet")
    resp = job_to_response(job)
    if fmt == "xlsx":
        content, media = export.to_xlsx(resp), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        content, media = export.to_csv(resp), "text/csv; charset=utf-8"
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{job_id}.{fmt}"'})


@router.post("/{job_id}/review", response_model=ReviewResult, summary="Store a human correction (kept as eval ground truth)")
async def review_job(
    job_id: str, review: ReviewRequest, api_key: ApiKey = Depends(require_api_key), session: AsyncSession = Depends(get_session)
) -> ReviewResult:
    job = await _own_job(session, job_id, api_key)
    if job.status not in REVIEWABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"job is {job.status}; only {', '.join(REVIEWABLE)} jobs can be reviewed")
    errors = validate.validate_invoice(review.data)
    validation = Validation(ok=not errors, errors=errors)
    session.add(JobReview(job_id=job.id, data=review.data.model_dump(mode="json"), validation=validation.model_dump(), notes=review.notes))
    job.status = "reviewed"
    await session.commit()
    return ReviewResult(job_id=job.id, status="reviewed", validation=validation)
