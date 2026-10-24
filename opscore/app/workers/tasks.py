"""Celery tasks for /v1/jobs (brief §4.3).

process_job:  PDF text -> extract_invoice (same pipeline as /v1/extract/sync) -> store -> callback.
              Retryable LLM/transport errors retry with exponential backoff + equal jitter (DECISIONS D25),
              max JOB_MAX_ATTEMPTS attempts; after that the job fails and the callback still goes out.
send_callback: signed POST to the job's callback_url, every attempt logged to webhook_deliveries,
              retried with backoff + jitter on non-2xx / network errors.
"""

import asyncio
import logging
import random
from datetime import UTC, datetime

from celery import Task
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import job_id_var
from app.models.db import Job, JobFile, WebhookDelivery
from app.services import callbacks, dedupe, pdf_text
from app.services.extract import apply_outcome, extract_invoice, failed_outcome, job_to_response
from app.services.llm import LLMClient, LLMError, build_llm
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)
settings = get_settings()
TERMINAL = ("done", "needs_review", "failed", "reviewed")

_engine = None


def db() -> Session:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.db_url(), pool_pre_ping=True)
    return Session(_engine, expire_on_commit=False)


def get_llm() -> LLMClient:
    """Tests replace this with a fake."""
    return build_llm(settings)


def enqueue_job(job_id: str) -> None:
    """Called by the API after the job row is committed. Tests replace this."""
    process_job.delay(job_id)


def enqueue_callback(job_id: str) -> None:
    send_callback.delay(job_id)


class RetryableJobError(Exception):
    """An LLM/transport failure worth another attempt."""


def _finish(session: Session, job: Job) -> None:
    job.completed_at = datetime.now(UTC)
    session.commit()


class JobTask(Task):
    def on_retry(self, exc, task_id, args, kwargs, einfo):
        job_id = args[0]
        with db() as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.status, job.last_error = "queued", str(exc)
                session.commit()
        log.warning("job attempt failed; retry scheduled", extra={"job_id": job_id, "error": str(exc), "retries_so_far": self.request.retries})

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        job_id = args[0]
        with db() as session:
            job = session.get(Job, job_id)
            if job is not None and job.status not in TERMINAL:
                code = "llm_unavailable" if isinstance(exc, RetryableJobError) else "processing_error"
                apply_outcome(job, failed_outcome(code, f"gave up after {job.attempts} attempt(s): {exc}", settings), pages=job.pages)
                job.last_error = str(exc)
                _finish(session, job)
        log.error("job failed", extra={"job_id": job_id, "error": str(exc)})
        enqueue_callback(job_id)


def job_backoff_s(attempt: int) -> float:
    """Exponential backoff with *equal* jitter: half fixed, half random. Celery's autoretry uses full jitter
    (0..delay), which can retry instantly while the LLM container is still restarting (DECISIONS D25).
    With the default 10 s base: retry 1 after 5-10 s, retry 2 after 10-20 s."""
    delay = min(120.0, settings.job_retry_backoff_s * 2 ** (attempt - 1))
    return delay / 2 + random.uniform(0, delay / 2)


@celery_app.task(bind=True, base=JobTask, name="opscore.process_job", max_retries=settings.job_max_attempts - 1)
def process_job(self, job_id: str) -> str:
    token = job_id_var.set(job_id)
    try:
        with db() as session:
            job = session.get(Job, job_id)
            if job is None or job.status in TERMINAL:
                return "skipped"  # unknown or already finished (e.g. redelivered after a worker restart)
            job.status = "processing"
            job.attempts += 1
            session.commit()
            attempt = job.attempts
            log.info("job attempt started", extra={"attempt": attempt, "max_attempts": settings.job_max_attempts})

            file = session.get(JobFile, job_id)
            try:
                doc = pdf_text.read_pdf_text(file.content, settings.extract_max_pages_async)
            except pdf_text.DocumentError as exc:
                apply_outcome(job, failed_outcome("unreadable_document", str(exc), settings), pages=None)
                _finish(session, job)
                enqueue_callback(job_id)
                return "failed"

            try:
                outcome = asyncio.run(extract_invoice(doc.text, llm=get_llm(), settings=settings))
            except LLMError as exc:
                if exc.retryable:
                    error = RetryableJobError(f"attempt {attempt}: {exc}")
                    if self.request.retries < self.max_retries:
                        raise self.retry(exc=error, countdown=job_backoff_s(attempt)) from exc
                    raise error from exc  # out of attempts -> on_failure marks the job failed and calls back
                apply_outcome(job, failed_outcome("llm_error", str(exc), settings), pages=doc.pages)
                _finish(session, job)
                enqueue_callback(job_id)
                return "failed"

            apply_outcome(job, outcome, pages=doc.pages)
            if job.dedupe_hash:
                job.duplicate_of = dedupe.find_duplicate_sync(session, job.dedupe_hash, api_key_id=job.api_key_id, exclude_job_id=job.id)
            _finish(session, job)
            log.info(
                "job finished",
                extra={"attempt": attempt, "status": job.status, "duplicate_of": job.duplicate_of, "confidence": outcome.confidence.overall},
            )
        enqueue_callback(job_id)
        return job.status
    finally:
        job_id_var.reset(token)


def callback_backoff_s(attempt: int) -> float:
    """5, 10, 20, 40, 80 s (capped at 300), each with full jitter."""
    return random.uniform(0, min(300, 5 * 2 ** (attempt - 1)))


@celery_app.task(bind=True, name="opscore.send_callback", max_retries=settings.callback_max_attempts - 1)
def send_callback(self, job_id: str) -> str:
    token = job_id_var.set(job_id)
    try:
        attempt = self.request.retries + 1
        with db() as session:
            job = session.get(Job, job_id)
            if job is None or not job.callback_url:
                return "no callback"
            body = job_to_response(job).model_dump_json().encode()
            try:
                result = callbacks.deliver(job.callback_url, body, job_id=job_id, settings=settings)
            except callbacks.CallbackBlocked as exc:
                session.add(WebhookDelivery(job_id=job_id, url=job.callback_url, attempt=attempt, error=f"blocked: {exc}"))
                session.commit()
                log.error("callback blocked by URL policy", extra={"error": str(exc)})
                return "blocked"
            session.add(
                WebhookDelivery(
                    job_id=job_id, url=job.callback_url, attempt=attempt,
                    status_code=result.status_code, latency_ms=result.latency_ms, error=result.error,
                )  # fmt: skip
            )
            session.commit()

        if result.ok:
            log.info("callback delivered", extra={"attempt": attempt, "status_code": result.status_code, "latency_ms": result.latency_ms})
            return "delivered"
        if result.permanent:
            log.error("callback refused by receiver; not retrying", extra={"attempt": attempt, "status_code": result.status_code, "error": result.error})
            return "refused"
        if attempt >= settings.callback_max_attempts:
            log.error("callback gave up", extra={"attempt": attempt, "status_code": result.status_code, "error": result.error})
            return "gave up"
        countdown = callback_backoff_s(attempt)
        log.warning("callback failed; retry scheduled", extra={"attempt": attempt, "status_code": result.status_code, "error": result.error, "retry_in_s": round(countdown, 1)})
        raise self.retry(countdown=countdown)
    finally:
        job_id_var.reset(token)
