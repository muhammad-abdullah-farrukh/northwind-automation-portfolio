"""Eval harness (DECISIONS D29): metric maths, cassettes, the gate, and the seed/temperature passthrough.
No model and no database: everything here is hand-made input."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.llm import AnthropicLLM, LLMError, LLMResult, OpenAICompatLLM
from evals import run_evals as rv
from evals.cassette import CassetteMiss, RecordingLLM, ReplayLLM

LINE = {"description": "Dashboard build", "qty": 2.0, "unit_price": 100.0, "amount": 200.0}


def test_match_lines_is_one_to_one_and_normalises_descriptions():
    want = [LINE, {**LINE, "description": "Support", "amount": 50.0, "unit_price": 25.0}]
    got = [{**LINE, "description": "  dashboard BUILD. "}, {**LINE, "description": "Dashboard build"}]
    assert rv.match_lines(got, want) == 1  # the second "Dashboard build" can't match "Support"
    assert rv.match_lines([{**LINE, "qty": 3.0}], [LINE]) == 0
    assert rv.match_lines([{**LINE, "amount": 200.004}], [LINE]) == 1  # within half a cent
    assert rv.match_lines([{"description": "x", "qty": None}], [LINE]) == 0


def test_reconciles():
    ok = {"line_items": [LINE], "subtotal": 200.0, "tax": 20.0, "total": 220.0}
    assert rv.reconciles(ok) is True
    assert rv.reconciles({**ok, "total": 230.0}) is False
    assert rv.reconciles({**ok, "subtotal": 210.0, "total": 230.0}) is False  # lines don't add up
    assert rv.reconciles(None) is None


def test_wrong_done_split_separates_money_from_text():
    diffs = ["due_date: None != '2026-01-01'", "line_items[1].qty: 3 != 2", "vendor: 'A' != 'B'", "total: 1 != 2"]
    assert rv.wrong_done_split("done", diffs) == (["line_items.qty", "total"], ["due_date", "vendor"])
    assert rv.wrong_done_split("needs_review", diffs) == ([], [])
    assert rv.wrong_done_split("done", []) == ([], [])


def invoice_row(file="a.pdf", *, correct=8, exact=True, status="done", tp=1, pred=1, exp=1, crit=(), other=(), ms=1000):
    fields = dict.fromkeys(rv.HEADER_FIELDS, False)
    for f in rv.HEADER_FIELDS[:correct]:
        fields[f] = True
    return {"file": file, "status": status, "expected_status": "done", "exact": exact, "field_correct": fields,
            "line_tp": tp, "line_pred": pred, "line_exp": exp, "reconciles": True, "label_reconciles": True,
            "first_call_invalid": False, "repair": False, "llm_ms": ms, "tokens": 100, "cost_usd": None,
            "critical_wrong_done": list(crit), "other_wrong_done": list(other)}  # fmt: skip


def test_invoice_metrics():
    rows = [invoice_row(), invoice_row("b.pdf", correct=6, exact=False, tp=1, pred=2, exp=1, crit=["total"], ms=3000)]
    m = rv.invoice_metrics(rows)
    assert m["field_accuracy"] == round(14 / 16, 4)
    assert (m["doc_exact"], m["status_ok"], m["wrong_done_docs"]) == (1, 2, 1)
    assert (m["line_precision"], m["line_recall"]) == (round(2 / 3, 4), 1.0)
    assert m["line_f1"] == round(2 * (2 / 3) / (2 / 3 + 1), 4)
    assert m["critical_cases"] == [["b.pdf", "total"]]
    assert m["cost_usd_total"] is None  # local model: no cost, not a made-up zero


def test_lead_metrics():
    rows = [
        {"expected": "hot", "final_tier": "hot", "ai_tier": "hot", "json_valid": True, "llm_ms": 10},
        {"expected": "spam", "final_tier": "spam", "ai_tier": "cold", "json_valid": True, "llm_ms": 20},
        {"expected": "cold", "final_tier": "hot", "ai_tier": None, "json_valid": False, "llm_ms": 30},
    ]
    m = rv.lead_metrics(rows)
    assert (m["final_correct"], m["ai_correct"], m["json_valid"]) == (2, 1, 2)
    assert (m["hot_hit"], m["hot_pred"], m["spam_hit"], m["spam_actual"]) == (1, 2, 1, 1)
    assert m["confusion_final"]["cold"]["hot"] == 1 and m["confusion_ai"]["cold"][None] == 1


class ScriptedLLM:
    provider = "openai_compat"

    def __init__(self, answers):
        self.answers = list(answers)

    async def complete_json(self, **_):
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return LLMResult(data=answer, model="m", input_tokens=1, output_tokens=2, latency_ms=5, cost_usd=None)


CALL = {"system": "s", "user": "u", "schema": {"type": "object"}, "tool_name": "t", "model": "m", "max_tokens": 9, "timeout": 1}
SETTINGS = {"provider": "openai_compat", "model_digest": "abc", "temperature": 0, "seed": 42, "json_mode": "tool", "reasoning_effort": None}


def test_cassette_round_trip_keeps_order_and_errors(tmp_path):
    rec = RecordingLLM(ScriptedLLM([{"n": 1}, {"n": 2}, LLMError("timeout", retryable=True)]), SETTINGS)

    async def record():
        a = await rec.complete_json(**CALL)
        b = await rec.complete_json(**CALL)  # same key twice: the 3x test runs
        with pytest.raises(LLMError):
            await rec.complete_json(**{**CALL, "user": "other"})
        return a, b

    a, b = asyncio.run(record())
    path = tmp_path / "c.jsonl"
    rec.save(path)
    replay = ReplayLLM(path)

    async def play():
        x = await replay.complete_json(**CALL)
        y = await replay.complete_json(**CALL)
        with pytest.raises(LLMError, match="timeout"):
            await replay.complete_json(**{**CALL, "user": "other"})
        with pytest.raises(CassetteMiss):
            await replay.complete_json(**CALL)  # both recorded answers are used up
        return x, y

    x, y = asyncio.run(play())
    assert (x.data, y.data) == (a.data, b.data) == ({"n": 1}, {"n": 2})
    assert replay.unused() == 0


@pytest.mark.parametrize("change", [{"seed": 7}, {"temperature": 0.7}, {"model_digest": "zzz"}, {"reasoning_effort": "none"}])
def test_cassette_key_covers_sampling_settings(tmp_path, change):
    rec = RecordingLLM(ScriptedLLM([{"n": 1}]), SETTINGS)
    asyncio.run(rec.complete_json(**CALL))
    rec.settings = {**SETTINGS, **change}  # pretend it had been recorded with different settings
    path = tmp_path / "c.jsonl"
    rec.save(path)
    with pytest.raises(CassetteMiss):
        asyncio.run(ReplayLLM(path).complete_json(**CALL))


def run_result(acc=0.9, crit=(), invalid=0, suite="invoices"):
    if suite == "invoices":
        m = {k: 0 for k in rv.GATED_INVOICE} | {"field_accuracy": acc, "critical_cases": [list(c) for c in crit], "first_call_invalid": invalid}
    else:
        m = {k: 0 for k in rv.GATED_LEAD} | {"n": 10, "final_correct": round(acc * 10), "json_valid": 10}
    return {"suite": suite, "slices": {"test": {"repeats": [{"metrics": m}]}}}


def test_gate_exact_replay():
    base = run_result()
    assert rv.gate(copy.deepcopy(base), base, exact=True) == []
    changed = run_result(acc=0.89)
    assert rv.gate(changed, base, exact=True)


def test_gate_live_thresholds_and_known_cases():
    base = run_result(acc=0.90, crit=[("a.pdf", "total")])
    assert rv.gate(run_result(acc=0.86, crit=[("a.pdf", "total")]), base, exact=False) == []  # -4 points: allowed
    assert rv.gate(run_result(acc=0.84), base, exact=False)  # -6 points: fails
    assert rv.gate(run_result(acc=0.90, crit=[("b.pdf", "subtotal")]), base, exact=False)  # a new money case fails
    assert rv.gate(run_result(acc=0.90, invalid=1), base, exact=False)  # more invalid JSON fails
    leads = run_result(acc=0.8, suite="leads")
    assert rv.gate(run_result(acc=0.7, suite="leads"), leads, exact=False)  # 10 points down


def test_spread_formats_ranges():
    assert rv.spread([3]) == "3"
    assert rv.spread([3, 3, 3]) == "3 (identical in 3 runs)"
    assert rv.spread([2, 4, 3], fmt=lambda v: f"{v}/5") == "3/5 (range 2/5 to 4/5, 3 runs)"


class CapturingClient:
    def __init__(self, response):
        self.kwargs = None
        self.response = response

    def with_options(self, **_):
        return self

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))

    @property
    def messages(self):
        return SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def openai_response():
    msg = SimpleNamespace(content='{"ok": true}')
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None, model="m")


@pytest.mark.parametrize("seed", [None, 42])
def test_seed_is_sent_only_when_set(seed):
    llm = OpenAICompatLLM(Settings(llm_provider="openai_compat", llm_base_url="http://x/v1", llm_seed=seed))
    llm.client = CapturingClient(openai_response())
    asyncio.run(llm.complete_json(**{k: v for k, v in CALL.items()}))
    assert llm.client.kwargs["temperature"] == 0
    assert ("seed" in llm.client.kwargs) is (seed is not None)
    if seed is not None:
        assert llm.client.kwargs["seed"] == 42


@pytest.mark.parametrize("temperature", [None, 0.0])
def test_anthropic_temperature_only_when_set(temperature):
    block = SimpleNamespace(type="tool_use", input={"ok": True})
    response = SimpleNamespace(content=[block], stop_reason="tool_use", model="claude-haiku-4-5",
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))  # fmt: skip
    llm = AnthropicLLM(Settings(llm_provider="anthropic", llm_temperature=temperature))
    llm.client = CapturingClient(response)
    asyncio.run(llm.complete_json(**CALL))
    assert ("temperature" in llm.client.kwargs) is (temperature is not None)
