"""X-API-Key auth. Keys are random, stored only as SHA-256 hashes, each with its own per-minute limit."""

import hashlib
import secrets
import time

from fastapi import Depends, Header, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_redis, get_session
from app.models.db import ApiKey

KEY_PREFIX = "oc_"


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> ApiKey:
    if not x_api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing X-API-Key header")
    key = await session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(x_api_key), ApiKey.active))
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")

    # Fixed one-minute window per key.
    window = int(time.time() // 60)
    counter = f"rl:{key.id}:{window}"
    used = await redis.incr(counter)
    if used == 1:
        await redis.expire(counter, 70)
    if used > key.rate_limit_per_min:
        retry_after = 60 - int(time.time() % 60)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"rate limit of {key.rate_limit_per_min}/min exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    return key
