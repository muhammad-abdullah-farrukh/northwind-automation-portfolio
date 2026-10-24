"""Process-wide resources, created in the FastAPI lifespan and read by dependencies."""

from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.services.llm import LLMClient, build_llm


@dataclass
class Resources:
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    llm: LLMClient


def build_resources(settings: Settings) -> Resources:
    engine = create_async_engine(settings.db_url(), pool_pre_ping=True, pool_size=10)
    return Resources(
        engine=engine,
        sessionmaker=async_sessionmaker(engine, expire_on_commit=False),
        redis=Redis.from_url(settings.redis_url, decode_responses=True),
        llm=build_llm(settings),
    )


async def close_resources(res: Resources) -> None:
    await res.redis.aclose()
    await res.engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.resources.sessionmaker() as session:
        yield session


def get_redis(request: Request) -> Redis:
    return request.app.state.resources.redis


def get_llm(request: Request) -> LLMClient:
    return request.app.state.resources.llm
