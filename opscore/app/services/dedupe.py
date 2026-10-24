"""Duplicate invoices: same vendor + invoice number + total, however the file itself differs."""

import hashlib
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.db import Job
from app.models.invoice import InvoiceData
from app.services.validate import money

_LEGAL_SUFFIXES = {"ltd", "limited", "inc", "llc", "gmbh", "co", "corp", "corporation", "plc", "pvt", "private", "company", "sa", "bv"}


def normalize_vendor(name: str) -> str:
    words = re.findall(r"[0-9a-z]+", name.lower())
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return "".join(words)


def normalize_invoice_no(value: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", value.upper())


def dedupe_hash(inv: InvoiceData) -> str:
    key = f"{normalize_vendor(inv.vendor)}|{normalize_invoice_no(inv.invoice_no)}|{money(inv.total):.2f}"
    return hashlib.sha256(key.encode()).hexdigest()


def _duplicate_stmt(digest: str, api_key_id: int, exclude_job_id: str | None):
    """Earliest earlier job for the same invoice that produced data, for the same client (API key) only:
    a cross-client match would leak that another client holds the same invoice (DECISIONS D20)."""
    stmt = select(Job.id).where(
        Job.dedupe_hash == digest, Job.api_key_id == api_key_id, Job.status.in_(("done", "needs_review", "reviewed"))
    )
    if exclude_job_id:
        stmt = stmt.where(Job.id != exclude_job_id)
    return stmt.order_by(Job.created_at, Job.id).limit(1)


async def find_duplicate(session: AsyncSession, digest: str, *, api_key_id: int, exclude_job_id: str | None = None) -> str | None:
    return await session.scalar(_duplicate_stmt(digest, api_key_id, exclude_job_id))


def find_duplicate_sync(session: Session, digest: str, *, api_key_id: int, exclude_job_id: str | None = None) -> str | None:
    return session.scalar(_duplicate_stmt(digest, api_key_id, exclude_job_id))
