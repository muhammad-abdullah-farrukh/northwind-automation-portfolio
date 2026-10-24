"""Tests run inside the api container against the compose Postgres/Redis, using a separate
database (opscore_test) and Redis db 15. The LLM and all outbound network calls are faked."""

import os

os.environ["POSTGRES_DB"] = "opscore_test"
os.environ["REDIS_URL"] = os.environ.get("REDIS_URL", "redis://redis:6379/0").rsplit("/", 1)[0] + "/15"
os.environ["LLM_PROVIDER"] = "none"
os.environ["LLM_MODEL_FAST"] = "fake-model"
os.environ["LLM_MODEL_EXTRACT"] = "fake-extract"
os.environ["SECRETS_DIR"] = "/tmp/opscore-test-secrets"
os.environ["CALLBACK_HMAC_SECRET"] = "test-callback-secret"
os.environ["CALLBACK_CA_FILE"] = ""

import httpx  # noqa: E402
import psycopg  # noqa: E402
import pytest  # noqa: E402
import redis  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.auth import generate_key, hash_key  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.models.db import ApiKey, Base  # noqa: E402
from app.services import email_checks, safe_fetch  # noqa: E402
from app.services.llm import LLMError, LLMResult  # noqa: E402

HOMEPAGE = (
    "<html><head><title>Acme Freight Cloud</title>"
    '<meta name="description" content="Route planning for trucking fleets"></head><body>'
    + "Acme Freight Cloud builds dispatch and route planning software for mid-size trucking fleets. " * 20
    + "</body></html>"
)


@pytest.fixture(scope="session")
def engine():
    s = get_settings()
    with psycopg.connect(
        host=s.postgres_host,
        port=s.postgres_port,
        user=s.postgres_user,
        password=s.postgres_password.get_secret_value(),
        dbname="postgres",
        autocommit=True,
    ) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (s.postgres_db,)).fetchone():
            conn.execute(f'CREATE DATABASE "{s.postgres_db}"')
    eng = create_engine(s.db_url())
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_state(request):
    if "engine" not in request.fixturenames:
        yield
        return
    eng = request.getfixturevalue("engine")
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE jobs, idempotency_records, domain_cache, api_keys RESTART IDENTITY CASCADE"))
    redis.Redis.from_url(get_settings().redis_url).flushdb()
    yield


def make_key(engine, name: str = "test", rate_limit: int = 100) -> str:
    raw = generate_key()
    with Session(engine) as session:
        session.add(ApiKey(name=name, key_prefix=raw[:8], key_hash=hash_key(raw), rate_limit_per_min=rate_limit))
        session.commit()
    return raw


@pytest.fixture
def api_key(engine) -> str:
    return make_key(engine)


class FakeLLM:
    provider = "fake"

    def __init__(self):
        self.calls = 0
        self.queue: list = []  # scripted responses for extraction tests: dicts to return, exceptions to raise
        self.behaviour = "ok"
        self.data = {
            "site_summary": "Dispatch and route planning software for mid-size trucking fleets.",
            "industry_guess": "Logistics SaaS",
            "employee_count_stated": 40,
            "confidence": 0.8,
        }

    async def complete_json(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs
        if self.queue:
            item = self.queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return LLMResult(data=item, model="fake-extract", input_tokens=900, output_tokens=300, latency_ms=7, cost_usd=None)
        if self.behaviour == "timeout":
            raise LLMError("timeout", retryable=True)
        data = {"site_summary": 42} if self.behaviour == "invalid" else dict(self.data)
        return LLMResult(data=data, model="fake-model", input_tokens=120, output_tokens=40, latency_ms=5, cost_usd=None)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def offline(monkeypatch):
    """No real DNS/HTTP: domains named no-mx-* have no MX; hosts named down-* refuse connections."""

    async def fake_mx(domain: str, timeout: float) -> bool:
        return not domain.startswith("no-mx")

    async def fake_fetch(url: str, **_) -> safe_fetch.FetchResult:
        if "down-" in url:
            raise httpx.ConnectError("connection refused")
        return safe_fetch.FetchResult(url, 200, HOMEPAGE)

    monkeypatch.setattr(email_checks, "check_mx", fake_mx)
    monkeypatch.setattr(safe_fetch, "fetch_homepage", fake_fetch)


@pytest.fixture
def client(engine, fake_llm, offline):
    from app.main import app

    with TestClient(app) as c:
        app.state.resources.llm = fake_llm
        yield c
