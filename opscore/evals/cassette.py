"""LLM cassettes for the eval harness (DECISIONS D29).

A live eval run records every raw model answer (or error) to a JSONL cassette. CI replays the cassette instead of
calling a model, so it is free, fast and deterministic, and still exercises all of OpsCore's own code: parsing,
validation, repair, confidence, routing and the LeadRouter scoring steps.

The key covers everything that can change a model's answer: provider, model, model digest, temperature, seed,
JSON mode, max_tokens, tool name, system prompt, user input and schema. Changing any of them (or a prompt file)
makes replay miss, which is a hard error: re-record with a live run. Repeated identical calls (the 3x test runs)
are kept in order, so the n-th replay of a key returns the n-th recorded answer.
"""

import hashlib
import json
from collections import defaultdict, deque
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.services.llm import LLMError, LLMResult

KEY_SETTINGS = ("provider", "model_digest", "temperature", "seed", "json_mode", "reasoning_effort")


class CassetteMiss(RuntimeError):
    """Replay found no recorded answer for a call: the inputs or settings changed since recording."""


def call_key(settings: dict[str, Any], *, system: str, user: str, schema: dict, tool_name: str, model: str, max_tokens: int) -> str:
    payload = {k: settings.get(k) for k in KEY_SETTINGS}
    payload.update(model=model, max_tokens=max_tokens, tool_name=tool_name, system=system, user=user, schema=schema)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class RecordingLLM:
    """Wraps a real client and records every answer under its call key."""

    def __init__(self, inner: Any, settings: dict[str, Any]):
        self.inner = inner
        self.provider = inner.provider
        self.settings = settings
        self.entries: list[dict] = []

    async def complete_json(self, *, system, user, schema, tool_name, model, max_tokens, timeout) -> LLMResult:
        key = call_key(self.settings, system=system, user=user, schema=schema, tool_name=tool_name, model=model, max_tokens=max_tokens)
        try:
            result = await self.inner.complete_json(system=system, user=user, schema=schema, tool_name=tool_name,
                                                    model=model, max_tokens=max_tokens, timeout=timeout)  # fmt: skip
        except LLMError as exc:
            self.entries.append({"key": key, "error": {"message": str(exc), "retryable": exc.retryable}})
            raise
        self.entries.append({"key": key, "result": asdict(result)})
        return result

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"settings": self.settings}, ensure_ascii=False) + "\n")
            for entry in self.entries:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class ReplayLLM:
    """Serves recorded answers; never calls a model."""

    def __init__(self, path: Path):
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines or "settings" not in lines[0]:
            raise ValueError(f"{path} is not a cassette (missing settings header)")
        self.settings = lines[0]["settings"]
        self.provider = self.settings.get("provider", "replay")
        self.queues: dict[str, deque] = defaultdict(deque)
        for entry in lines[1:]:
            self.queues[entry["key"]].append(entry)

    async def complete_json(self, *, system, user, schema, tool_name, model, max_tokens, timeout) -> LLMResult:
        key = call_key(self.settings, system=system, user=user, schema=schema, tool_name=tool_name, model=model, max_tokens=max_tokens)
        queue = self.queues.get(key)
        if not queue:
            raise CassetteMiss(f"no recorded answer for this {tool_name} call (key {key[:12]}); inputs, prompt or settings "
                               "changed since recording, so re-record with a live run")  # fmt: skip
        entry = queue.popleft()
        if "error" in entry:
            raise LLMError(entry["error"]["message"], retryable=entry["error"]["retryable"])
        return LLMResult(**entry["result"])

    def unused(self) -> int:
        return sum(len(q) for q in self.queues.values())
