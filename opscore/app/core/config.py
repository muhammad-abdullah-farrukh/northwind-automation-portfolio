from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """All runtime config comes from the environment (docker compose passes .env through)."""

    model_config = SettingsConfigDict(extra="ignore")

    app_version: str = "0.1.0"

    postgres_user: str = "opscore"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "opscore"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    redis_url: str = "redis://redis:6379/0"

    # LLM: provider-agnostic. "anthropic" also covers Anthropic-compatible gateways via llm_base_url.
    llm_provider: Literal["anthropic", "openai_compat", "none"] = "anthropic"
    llm_base_url: str | None = None
    llm_api_key: SecretStr = SecretStr("")
    llm_model_fast: str = ""
    llm_model_extract: str = ""
    # tool = forced tool_use (most portable across gateways); structured = output_config json_schema;
    # prompt = plain JSON instructions + parsing.
    llm_json_mode: Literal["tool", "structured", "prompt"] = "tool"
    llm_timeout_s: float = 4.0
    # OpenAI-compatible only: e.g. "none" turns off hidden reasoning on thinking models served by
    # Ollama (measured: granite4.2:3b 64 -> 10 completion tokens on a trivial JSON call). Empty = not sent.
    llm_reasoning_effort: str | None = None
    # Eval reproducibility (DECISIONS D29). Unset in production, so behaviour is unchanged.
    # llm_seed is sent to OpenAI-compatible providers (Ollama honours it); llm_temperature overrides the
    # Anthropic default of 1.0. OpenAI-compatible calls already use temperature 0.
    llm_seed: int | None = None
    llm_temperature: float | None = None

    # /v1/leads/enrich
    enrich_budget_s: float = 4.8
    fetch_timeout_s: float = 2.5
    fetch_max_bytes: int = 512_000
    fetch_max_redirects: int = 3
    dns_timeout_s: float = 3.0
    domain_cache_days: int = 30
    page_text_max_chars: int = 6000

    # /v1/extract/sync
    llm_extract_timeout_s: float = 60.0
    extract_max_pages_sync: int = 5
    upload_max_bytes: int = 10_000_000
    review_threshold: float = 0.85

    # /v1/jobs (async, Celery)
    extract_max_pages_async: int = 30
    job_max_attempts: int = 3  # brief: max 3 attempts on retryable LLM/transport errors
    job_retry_backoff_s: int = 10  # exponential with equal jitter: retry 1 after 5-10 s, retry 2 after 10-20 s
    callback_hmac_secret: SecretStr = SecretStr("")
    callback_timeout_s: float = 10.0
    callback_max_attempts: int = 6
    # "host:port->target" pairs. Only these non-public callback hosts are allowed, and the connection goes to the
    # target while TLS still checks the original name (n8n's resume URLs say localhost:5678). DECISIONS D26.
    callback_host_map: str = "localhost:5678->host.docker.internal"
    callback_ca_file: str | None = None  # pinned CA for mapped hosts, e.g. n8n's self-signed cert

    default_rate_limit_per_min: int = 60
    secrets_dir: str = "/app/.secrets"
    prompts_dir: str = "/app/prompts"

    def db_url(self, database: str | None = None) -> URL:
        # psycopg 3 serves both the async (API) and sync (CLI, Alembic, Celery) engines.
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=database or self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
