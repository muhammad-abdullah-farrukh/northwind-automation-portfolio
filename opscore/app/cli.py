"""Admin CLI: `python -m app.cli <command>` inside the api container.

Secrets never go to stdout: create-key writes the key to .secrets/<name>.key (git-ignored,
bind-mounted from the host) and prints only the path and a short prefix.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.auth import generate_key, hash_key
from app.core.config import get_settings
from app.models.db import ApiKey
from app.services.llm import LLMError, build_llm


def create_key(name: str, rate_limit: int) -> None:
    settings = get_settings()
    raw = generate_key()
    engine = create_engine(settings.db_url())
    with Session(engine) as session:
        key = session.scalar(select(ApiKey).where(ApiKey.name == name))
        action = "rotated" if key else "created"
        if key is None:
            key = ApiKey(name=name)
            session.add(key)
        key.key_hash, key.key_prefix, key.rate_limit_per_min, key.active = hash_key(raw), raw[:8], rate_limit, True
        session.commit()

    secrets_dir = Path(settings.secrets_dir)
    secrets_dir.mkdir(parents=True, exist_ok=True)
    path = secrets_dir / f"{name}.key"
    path.write_text(raw + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    print(f"API key '{name}' {action} (prefix {raw[:8]}..., {rate_limit}/min). Written to .secrets/{name}.key")


def list_keys() -> None:
    engine = create_engine(get_settings().db_url())
    with Session(engine) as session:
        for key in session.scalars(select(ApiKey).order_by(ApiKey.id)):
            print(f"{key.id:>3}  {key.name:<16} {key.key_prefix}...  {key.rate_limit_per_min:>4}/min  active={key.active}")


async def llm_ping(list_models: bool) -> int:
    settings = get_settings()
    llm = build_llm(settings)
    host = settings.llm_base_url or "(provider default)"
    print(f"provider={settings.llm_provider} base_url={host} json_mode={settings.llm_json_mode}")
    if list_models:
        try:
            print("models:", ", ".join(await llm.list_models()))
        except Exception as exc:  # noqa: BLE001
            detail = str(exc).replace(settings.llm_api_key.get_secret_value() or "\0", "***")[:240]
            print(f"models: could not list ({type(exc).__name__}: {detail})")
    status = 0
    for label, model in (("fast", settings.llm_model_fast), ("extract", settings.llm_model_extract)):
        if not model:
            print(f"{label}: (no model configured)")
            continue
        try:
            res = await llm.complete_json(
                system="You are a health check.",
                user="Set ok to true.",
                schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                tool_name="health_check",
                model=model,
                max_tokens=1024,
                timeout=60,
            )
            print(f"{label}: OK model={res.model} latency_ms={res.latency_ms} tokens={res.input_tokens}/{res.output_tokens} data={res.data}")
        except LLMError as exc:
            status = 1
            print(f"{label}: FAIL model={model} error={exc} retryable={exc.retryable} detail={exc.detail}")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    ck = sub.add_parser("create-key", help="create or rotate an API key; writes it to .secrets/<name>.key")
    ck.add_argument("--name", required=True)
    ck.add_argument("--rate-limit", type=int, default=get_settings().default_rate_limit_per_min)
    sub.add_parser("list-keys", help="list API keys (names and prefixes only)")
    lp = sub.add_parser("llm-ping", help="check the configured LLM endpoint and models")
    lp.add_argument("--list-models", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "create-key":
        create_key(args.name, args.rate_limit)
    elif args.command == "list-keys":
        list_keys()
    elif args.command == "llm-ping":
        return asyncio.run(llm_ping(args.list_models))
    return 0


if __name__ == "__main__":
    sys.exit(main())
