"""Idempotency-Key handling, Stripe-style.

A key is scoped to (api key, endpoint). The first request claims it with an in_progress row,
runs, and stores its response. A replay with the same body gets the stored response back
with `Idempotent-Replay: true`; the same key with a different body is a 409.
"""

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import IdempotencyRecord

log = logging.getLogger(__name__)

Handler = Callable[[], Awaitable[tuple[int, Any]]]


def request_hash(body: Any) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_key(idem_key: str) -> str:
    if not (1 <= len(idem_key) <= 255) or not idem_key.isprintable():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key must be 1-255 printable characters")
    return idem_key


def _replay(record: IdempotencyRecord, body_hash: str) -> JSONResponse:
    if record.request_hash != body_hash:
        raise HTTPException(status.HTTP_409_CONFLICT, "Idempotency-Key was already used with a different request body")
    if record.state != "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "a request with this Idempotency-Key is still in progress")
    log.info("idempotent replay", extra={"idem_key": record.idem_key})
    return JSONResponse(record.response_body, status_code=record.status_code or 200, headers={"Idempotent-Replay": "true"})


async def run_idempotent(
    session: AsyncSession,
    *,
    api_key_id: int,
    endpoint: str,
    idem_key: str | None,
    body: Any,
    handler: Handler,
) -> JSONResponse:
    if idem_key is None:
        code, payload = await handler()
        return JSONResponse(payload, status_code=code)

    validate_key(idem_key)
    body_hash = request_hash(body)
    scope = (
        IdempotencyRecord.api_key_id == api_key_id,
        IdempotencyRecord.endpoint == endpoint,
        IdempotencyRecord.idem_key == idem_key,
    )

    claimed = await session.scalar(
        insert(IdempotencyRecord)
        .values(api_key_id=api_key_id, endpoint=endpoint, idem_key=idem_key, request_hash=body_hash)
        .on_conflict_do_nothing(constraint="uq_idem_scope")
        .returning(IdempotencyRecord.id)
    )
    await session.commit()
    if claimed is None:
        existing = await session.scalar(select(IdempotencyRecord).where(*scope))
        return _replay(existing, body_hash)

    try:
        code, payload = await handler()
    except HTTPException as exc:
        if exc.status_code >= 500:
            await _release(session, claimed)
            raise
        # Deterministic client errors (e.g. invalid email) are stored and replayed too.
        code, payload = exc.status_code, {"detail": exc.detail}
    except BaseException:
        await _release(session, claimed)
        raise

    record = await session.get(IdempotencyRecord, claimed)
    record.state, record.status_code, record.response_body = "completed", code, payload
    await session.commit()
    return JSONResponse(payload, status_code=code)


async def _release(session: AsyncSession, record_id: int) -> None:
    """Free the key so the client can retry after a server-side failure."""
    await session.rollback()
    await session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.id == record_id))
    await session.commit()
