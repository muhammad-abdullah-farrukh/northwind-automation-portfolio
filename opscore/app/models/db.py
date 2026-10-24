from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    key_prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)  # sha256 hex of the full key
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=60)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("api_key_id", "endpoint", "idem_key", name="uq_idem_scope"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(String(128))
    idem_key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="in_progress")  # in_progress | completed
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # json, not jsonb: jsonb reorders keys, and replays must be byte-identical to the original
    response_body: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    """One document through the extraction pipeline. Sync (/v1/extract/sync) and async (/v1/jobs, P4) share it."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    api_key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(8))  # sync | async
    schema_name: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), index=True)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dedupe_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    duplicate_of: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    callback_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class JobFile(Base):
    """The uploaded document, kept in Postgres (<=10 MB) so the worker reads it transactionally (DECISIONS D24)."""

    __tablename__ = "job_files"

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary)
    size_bytes: Mapped[int] = mapped_column(Integer)


class WebhookDelivery(Base):
    """One row per callback attempt, success or not."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobReview(Base):
    """A human correction. Kept apart from jobs.data so evals can compare model output with the truth."""

    __tablename__ = "job_reviews"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    data: Mapped[dict] = mapped_column(JSONB)
    validation: Mapped[dict] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DomainCache(Base):
    __tablename__ = "domain_cache"

    domain: Mapped[str] = mapped_column(String(253), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
