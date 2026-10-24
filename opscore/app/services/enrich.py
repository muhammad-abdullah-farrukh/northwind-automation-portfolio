"""POST /v1/leads/enrich — email checks + homepage read + LLM guess, inside a fixed time budget.

Anything slow or flaky (DNS, the site, the LLM) degrades to nulls plus a note instead of failing,
so the Zap always gets the full contract back.
"""

import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.db import DomainCache
from app.models.schemas import EnrichRequest, EnrichResponse, SiteGuess
from app.services import email_checks, safe_fetch, scoring
from app.services.llm import LLMClient, LLMError

log = logging.getLogger(__name__)

PROMPT_VERSION = "site_enrich_v3"  # v3: model reports a stated headcount, code bands it (DECISIONS D23)
LLM_NOTE = "industry and size are LLM guesses"
MIN_LLM_SECONDS = 0.5


@lru_cache
def load_prompt(prompts_dir: str, name: str) -> str:
    return (Path(prompts_dir) / f"{name}.md").read_text(encoding="utf-8").strip()


@dataclass
class SiteAnalysis:
    website_reachable: bool = False
    site_summary: str | None = None
    industry_guess: str | None = None
    size_band_guess: str | None = None
    text_chars: int = 0
    llm_ok: bool = False
    llm_confidence: float = 0.0


def site_target(website: str | None, email_domain: str, personal_address: bool) -> tuple[str, str] | None:
    """(url, cache_domain) to analyse: the form's website, else the email domain for company addresses."""
    if website and website.strip():
        url = safe_fetch.normalize_site_url(website)
    elif not personal_address:
        url = f"https://{email_domain}"
    else:
        return None
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return None
    return url, host.removeprefix("www.")


async def enrich_lead(req: EnrichRequest, *, session: AsyncSession, llm: LLMClient, settings: Settings) -> EnrichResponse:
    started = time.perf_counter()
    deadline = started + settings.enrich_budget_s
    try:
        email, domain = email_checks.normalize_email(req.email)
    except email_checks.InvalidEmail as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"invalid email: {exc}") from exc

    free = email_checks.is_free_mail(domain)
    disposable = email_checks.is_disposable(domain)
    mx_task = asyncio.create_task(email_checks.check_mx(domain, settings.dns_timeout_s))

    notes = [LLM_NOTE]
    cached = False
    site = SiteAnalysis()
    target = site_target(req.website, domain, free or disposable)
    if target is None:
        notes.append("no company website to analyse")
    else:
        url, cache_domain = target
        payload = await _load_cache(session, cache_domain, settings.domain_cache_days)
        if payload is not None:
            site, cached = SiteAnalysis(**payload), True
        else:
            site, site_notes = await _analyse_site(url, req.company, llm=llm, settings=settings, deadline=deadline)
            notes += site_notes
            if site.llm_ok:  # only cache complete results, so a flaky run can't pin nulls for 30 days
                await _store_cache(session, cache_domain, asdict(site))

    mx_result = await mx_task
    mx_valid = bool(mx_result)
    if mx_result is None:
        notes.append("mx lookup timed out")
    result = EnrichResponse(
        email=email,
        domain=domain,
        mx_valid=mx_valid,
        is_free_mail=free,
        is_disposable=disposable,
        website_reachable=site.website_reachable,
        site_summary=site.site_summary,
        industry_guess=site.industry_guess,
        size_band_guess=site.size_band_guess,
        rule_score=scoring.rule_score(
            mx_valid=mx_valid,
            is_free_mail=free,
            is_disposable=disposable,
            website_reachable=site.website_reachable,
            industry_guess=site.industry_guess,
            size_band_guess=site.size_band_guess,
        ),
        enrich_confidence=scoring.enrich_confidence(
            website_reachable=site.website_reachable,
            text_chars=site.text_chars,
            llm_ok=site.llm_ok,
            llm_confidence=site.llm_confidence,
            industry_guess=site.industry_guess,
            size_band_guess=site.size_band_guess,
        ),
        cached=cached,
        note="; ".join(notes),
    )
    log.info(
        "lead enriched",
        extra={
            "domain": domain,
            "cached": cached,
            "rule_score": result.rule_score,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    return result


async def _analyse_site(
    url: str, company: str | None, *, llm: LLMClient, settings: Settings, deadline: float
) -> tuple[SiteAnalysis, list[str]]:
    site = SiteAnalysis()
    try:
        fetched = await safe_fetch.fetch_homepage(
            url,
            timeout=min(settings.fetch_timeout_s, max(0.1, deadline - time.perf_counter())),
            max_bytes=settings.fetch_max_bytes,
            max_redirects=settings.fetch_max_redirects,
        )
    except safe_fetch.BlockedURL as exc:
        return site, [f"website not fetched: {exc}"]
    except httpx.HTTPError as exc:
        return site, [f"website unreachable: {type(exc).__name__}"]
    if fetched.status_code >= 400:
        return site, [f"website returned HTTP {fetched.status_code}"]

    text = safe_fetch.extract_page_text(fetched.text, settings.page_text_max_chars)
    site.website_reachable, site.text_chars = True, len(text)

    remaining = deadline - time.perf_counter()
    if remaining < MIN_LLM_SECONDS:
        return site, ["llm skipped: time budget used up by the website fetch"]
    user = (
        f"Company name from the form: {company or 'not given'}\n"
        f"Website: {fetched.final_url}\n\n<homepage_text>\n{text}\n</homepage_text>"
    )
    try:
        res = await llm.complete_json(
            system=load_prompt(settings.prompts_dir, PROMPT_VERSION),
            user=user,
            schema=SiteGuess.model_json_schema(),
            tool_name="record_site_guess",
            model=settings.llm_model_fast,
            max_tokens=1024,
            timeout=min(settings.llm_timeout_s, remaining - 0.1),
        )
        guess = SiteGuess.model_validate(res.data)
    except LLMError as exc:
        log.warning("llm call failed", extra={"error": str(exc), "detail": exc.detail, "retryable": exc.retryable})
        return site, [f"llm unavailable: {exc}"]
    except ValidationError as exc:
        return site, [f"llm output failed validation ({exc.error_count()} errors)"]

    log.info(
        "llm call",
        extra={
            "prompt_version": PROMPT_VERSION,
            "model": res.model,
            "input_tokens": res.input_tokens,
            "output_tokens": res.output_tokens,
            "llm_latency_ms": res.latency_ms,
            "cost_usd_estimate": res.cost_usd,
        },
    )
    site.site_summary = guess.site_summary
    site.industry_guess = guess.industry_guess
    site.size_band_guess = scoring.size_band_for(guess.employee_count_stated)
    site.llm_ok, site.llm_confidence = True, guess.confidence
    return site, []


async def _load_cache(session: AsyncSession, domain: str, days: int) -> dict | None:
    row = await session.get(DomainCache, domain)
    if row is None or row.fetched_at < datetime.now(UTC) - timedelta(days=days):
        return None
    return row.payload


async def _store_cache(session: AsyncSession, domain: str, payload: dict) -> None:
    stmt = insert(DomainCache).values(domain=domain, payload=payload)
    stmt = stmt.on_conflict_do_update(index_elements=[DomainCache.domain], set_={"payload": payload, "fetched_at": func.now()})
    await session.execute(stmt)
    await session.commit()
