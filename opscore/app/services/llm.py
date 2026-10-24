"""Provider-agnostic "give me JSON matching this schema" LLM calls.

Backends:
- AnthropicLLM: the official Anthropic SDK, optionally pointed at an Anthropic-compatible
  gateway through LLM_BASE_URL.
- OpenAICompatLLM: any OpenAI-compatible server (Ollama, vLLM, ...).
- DisabledLLM: LLM_PROVIDER=none; every call fails fast and callers degrade.

Callers validate the returned dict with Pydantic; this module only guarantees "a dict or LLMError".
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic
import openai

from app.core.config import Settings
from app.services.pricing import estimate_cost_usd

log = logging.getLogger(__name__)


@dataclass
class LLMResult:
    data: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float | None


class LLMError(Exception):
    """str(exc) is short and safe to put in API responses; .detail holds the provider's message for logs."""

    def __init__(self, message: str, *, retryable: bool = False, detail: str | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.detail = detail


class LLMClient(Protocol):
    provider: str

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        tool_name: str,
        model: str,
        max_tokens: int,
        timeout: float,
    ) -> LLMResult: ...


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic emits $defs/$ref; inline them so gateways and local models without $ref support still work."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return resolve(defs[ref.removeprefix("#/$defs/")])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_json_text(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of free text (handles ```json fences and chatter)."""
    match = _JSON_OBJECT.search(text or "")
    if not match:
        raise LLMError("model returned no JSON object")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMError(f"model returned invalid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise LLMError("model returned JSON that is not an object")
    return data


def _status_error(exc: anthropic.APIStatusError | openai.APIStatusError, secret: str) -> LLMError:
    detail = str(getattr(exc, "message", "") or "")
    if secret:
        detail = detail.replace(secret, "***")
    return LLMError(f"provider returned {exc.status_code}", retryable=exc.status_code >= 500, detail=detail[:500])


def _json_instruction(schema: dict[str, Any]) -> str:
    return "\n\nRespond with only one JSON object (no prose, no code fences) matching this JSON Schema:\n" + json.dumps(schema)


class AnthropicLLM:
    provider = "anthropic"

    def __init__(self, settings: Settings):
        self.json_mode = settings.llm_json_mode
        self.temperature = settings.llm_temperature
        self._secret = settings.llm_api_key.get_secret_value()
        self.client = anthropic.AsyncAnthropic(
            api_key=settings.llm_api_key.get_secret_value() or None,
            base_url=settings.llm_base_url or None,
            max_retries=0,  # retries are the caller's policy (Celery backoff in P4)
        )

    async def complete_json(self, *, system, user, schema, tool_name, model, max_tokens, timeout) -> LLMResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.json_mode == "tool":
            kwargs["tools"] = [{"name": tool_name, "description": f"Record the {tool_name} result.", "input_schema": schema}]
            kwargs["tool_choice"] = {"type": "tool", "name": tool_name}
        elif self.json_mode == "structured":
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": {**schema, "additionalProperties": False}}}
        else:
            kwargs["system"] = system + _json_instruction(schema)

        started = time.perf_counter()
        try:
            msg = await self.client.with_options(timeout=timeout).messages.create(**kwargs)
        except anthropic.APITimeoutError as exc:
            raise LLMError("timeout", retryable=True) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("connection error", retryable=True) from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("rate limited (429)", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise _status_error(exc, self._secret) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if msg.stop_reason == "refusal":
            raise LLMError("model refused")
        tool_input = next((b.input for b in msg.content if b.type == "tool_use"), None)
        if isinstance(tool_input, dict):
            data = tool_input
        else:
            data = parse_json_text("".join(b.text for b in msg.content if b.type == "text"))

        return LLMResult(
            data=data,
            model=msg.model or model,
            input_tokens=msg.usage.input_tokens,
            output_tokens=msg.usage.output_tokens,
            latency_ms=latency_ms,
            cost_usd=estimate_cost_usd(model, msg.usage.input_tokens, msg.usage.output_tokens),
        )

    async def list_models(self) -> list[str]:
        page = await self.client.models.list(limit=100)
        return [m.id for m in page.data]


class OpenAICompatLLM:
    provider = "openai_compat"

    def __init__(self, settings: Settings):
        self.json_mode = settings.llm_json_mode
        self.reasoning_effort = settings.llm_reasoning_effort or None
        self.seed = settings.llm_seed
        self._secret = settings.llm_api_key.get_secret_value()
        self.client = openai.AsyncOpenAI(
            api_key=settings.llm_api_key.get_secret_value() or "not-needed",  # Ollama ignores the key
            base_url=settings.llm_base_url,
            max_retries=0,
        )

    async def complete_json(self, *, system, user, schema, tool_name, model, max_tokens, timeout) -> LLMResult:
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens, "temperature": 0}
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if self.seed is not None:
            kwargs["seed"] = self.seed
        if self.json_mode == "prompt":
            kwargs["messages"] = [{"role": "system", "content": system + _json_instruction(schema)}, {"role": "user", "content": user}]
        else:
            kwargs["messages"] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": tool_name, "schema": schema}}

        started = time.perf_counter()
        try:
            resp = await self.client.with_options(timeout=timeout).chat.completions.create(**kwargs)
        except openai.APITimeoutError as exc:
            raise LLMError("timeout", retryable=True) from exc
        except openai.APIConnectionError as exc:
            raise LLMError("connection error", retryable=True) from exc
        except openai.RateLimitError as exc:
            raise LLMError("rate limited (429)", retryable=True) from exc
        except openai.APIStatusError as exc:
            raise _status_error(exc, self._secret) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if not resp.choices:
            raise LLMError("provider returned no choices")
        data = parse_json_text(resp.choices[0].message.content or "")
        usage = resp.usage
        in_tok, out_tok = (usage.prompt_tokens, usage.completion_tokens) if usage else (0, 0)
        return LLMResult(
            data=data,
            model=resp.model or model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency_ms,
            cost_usd=estimate_cost_usd(model, in_tok, out_tok),
        )

    async def list_models(self) -> list[str]:
        page = await self.client.models.list()
        return [m.id for m in page.data]


class DisabledLLM:
    provider = "none"

    async def complete_json(self, **_: Any) -> LLMResult:
        raise LLMError("LLM disabled (LLM_PROVIDER=none)")

    async def list_models(self) -> list[str]:
        return []


def build_llm(settings: Settings) -> LLMClient:
    if settings.llm_provider == "anthropic":
        return AnthropicLLM(settings)
    if settings.llm_provider == "openai_compat":
        return OpenAICompatLLM(settings)
    return DisabledLLM()
