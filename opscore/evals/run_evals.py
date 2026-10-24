"""OpsCore eval harness (brief §4.5, DECISIONS D29). Every number it writes comes from the run it describes.

Two suites, both through production code:
- invoices: evals/data/invoices (dev 1-20, val 21-40, test_same_template 41-60) and evals/data/invoices_alt
  (test_new_layout, a second template). Runs app.services.extract.extract_invoice for a given prompt version.
- leads: evals/data/leads.jsonl (leads_dev, leads_test). Runs LeadRouter's prepare_lead.py, the lead_icp_v1 prompt
  through OpsCore's LLM client, then score_lead.py, the same chain as the Zap (whose AI step uses Zapier's model).

Test slices can be repeated (--repeats) to show run-to-run spread. --mode record saves a cassette, --mode replay
uses one (no model calls). Subcommands (inside the api container):

    python -m evals.run_evals run --suite invoices --prompt invoice_extract_v2 --repeats 3 --mode record --tag v2
    python -m evals.run_evals report evals/results/run_*.json --out evals/report.md
    python -m evals.run_evals baseline evals/results/run_A.json ... --out evals/baseline.json
    python -m evals.run_evals gate --baseline evals/baseline.json evals/results/run_B.json
    python -m evals.run_evals ci --baseline evals/baseline.json     # replay every baseline run, then gate
"""

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, SecretStr, ValidationError

from app.core.config import Settings
from app.services import pdf_text
from app.services.enrich import load_prompt
from app.services.extract import extract_invoice
from app.services.llm import LLMError, build_llm
from evals.bench_llm import field_diffs, pct
from evals.cassette import CassetteMiss, RecordingLLM, ReplayLLM

DATA = Path("evals/data")
RESULTS = Path("evals/results")
CASSETTES = Path("evals/cassettes")
LEADROUTER = next((p for p in (Path("../leadrouter"), Path("/leadrouter")) if p.exists()), Path("../leadrouter"))

HEADER_FIELDS = ("vendor", "invoice_no", "invoice_date", "due_date", "currency", "subtotal", "tax", "total")
# A wrong value in one of these reaching status "done" is the failure the gate never accepts (D29).
CRITICAL_FIELDS = {"invoice_no", "currency", "subtotal", "tax", "total", "line_items", "line_items.qty", "line_items.unit_price", "line_items.amount"}
INVOICE_SLICES = ("dev", "val", "test_same_template", "test_new_layout")
LEAD_SLICES = ("leads_dev", "leads_test")
TIERS = ("hot", "warm", "cold", "spam")
LEAD_PROMPT = "lead_icp_v1"


# ---------------------------------------------------------------- metrics (pure functions, unit-tested)
def norm_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower()).strip(" .,-")


def match_lines(got: list[dict], want: list[dict]) -> int:
    """One-to-one matches: same normalised description, qty, unit price (±0.005) and amount (±0.005)."""
    used: set[int] = set()
    hits = 0
    for w in want:
        for i, g in enumerate(got):
            if i in used:
                continue
            try:
                same = (norm_text(g.get("description")) == norm_text(w["description"])
                        and abs(float(g.get("qty")) - float(w["qty"])) < 1e-6
                        and abs(float(g.get("unit_price")) - float(w["unit_price"])) <= 0.005
                        and abs(float(g.get("amount")) - float(w["amount"])) <= 0.005)  # fmt: skip
            except (TypeError, ValueError):
                same = False
            if same:
                used.add(i)
                hits += 1
                break
    return hits


def reconciles(data: dict | None) -> bool | None:
    """Lines add up to the subtotal and subtotal + tax to the total, each within 0.01."""
    if not data:
        return None
    try:
        lines = data.get("line_items") or []
        ok_lines = not lines or abs(sum(float(li["amount"]) for li in lines) - float(data["subtotal"])) <= 0.01
        return ok_lines and abs(float(data["subtotal"]) + float(data["tax"]) - float(data["total"])) <= 0.01
    except (KeyError, TypeError, ValueError):
        return False


def diff_field(diff: str) -> str:
    """'line_items[1].qty: 3 != 2' -> 'line_items.qty'; 'due_date: None != ...' -> 'due_date'."""
    return re.sub(r"\[\d+\]", "", diff.split(":", 1)[0])


def wrong_done_split(status: str | None, diffs: list[str]) -> tuple[list[str], list[str]]:
    if status != "done" or not diffs:
        return [], []
    fields = sorted({diff_field(d) for d in diffs})
    return [f for f in fields if f in CRITICAL_FIELDS], [f for f in fields if f not in CRITICAL_FIELDS]


def invoice_metrics(rows: list[dict]) -> dict:
    n = len(rows)
    per_field = {f: sum(r["field_correct"].get(f, False) for r in rows) for f in HEADER_FIELDS}
    tp, pred, exp = (sum(r[k] for r in rows) for k in ("line_tp", "line_pred", "line_exp"))
    precision = tp / pred if pred else 0.0
    recall = tp / exp if exp else 0.0
    rec_rows = [r for r in rows if r["label_reconciles"]]
    llm_ms = [r["llm_ms"] for r in rows if r.get("llm_ms") is not None]
    costs = [r["cost_usd"] for r in rows]
    return {
        "n": n,
        "field_accuracy": round(sum(per_field.values()) / (len(HEADER_FIELDS) * n), 4) if n else None,
        "per_field": per_field,
        "doc_exact": sum(r["exact"] for r in rows),
        "status_ok": sum(r["status"] == r["expected_status"] for r in rows),
        "line_tp": tp, "line_pred": pred, "line_exp": exp,
        "line_precision": round(precision, 4), "line_recall": round(recall, 4),
        "line_f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "reconciles": sum(bool(r["reconciles"]) for r in rec_rows), "reconciles_n": len(rec_rows),
        "first_call_invalid": sum(r["first_call_invalid"] for r in rows),
        "llm_errors": sum(r["status"] == "llm_error" for r in rows),
        "repairs": sum(r["repair"] for r in rows),
        "wrong_done_docs": sum(bool(r["critical_wrong_done"] or r["other_wrong_done"]) for r in rows),
        "critical_cases": sorted([r["file"], f] for r in rows for f in r["critical_wrong_done"]),
        "other_wrong_done": {f: sum(f in r["other_wrong_done"] for r in rows) for f in sorted({f for r in rows for f in r["other_wrong_done"]})},
        "llm_ms_p50": int(statistics.median(llm_ms)) if llm_ms else None,
        "llm_ms_p95": pct(llm_ms, 0.95) if llm_ms else None,
        "tokens_mean": round(statistics.mean(r["tokens"] for r in rows)) if n else None,
        "cost_usd_total": round(sum(costs), 6) if costs and all(c is not None for c in costs) else None,
    }


def lead_metrics(rows: list[dict]) -> dict:
    n = len(rows)

    def confusion(key: str) -> dict:
        return {e: {p: sum(r["expected"] == e and r[key] == p for r in rows) for p in (*TIERS, None)} for e in TIERS}

    def precision_recall(tier: str) -> tuple[int, int, int]:
        predicted = sum(r["final_tier"] == tier for r in rows)
        actual = sum(r["expected"] == tier for r in rows)
        hit = sum(r["final_tier"] == tier and r["expected"] == tier for r in rows)
        return hit, predicted, actual

    llm_ms = [r["llm_ms"] for r in rows if r.get("llm_ms") is not None]
    spam_hit, spam_pred, spam_act = precision_recall("spam")
    hot_hit, hot_pred, hot_act = precision_recall("hot")
    return {
        "n": n,
        "final_correct": sum(r["final_tier"] == r["expected"] for r in rows),
        "ai_correct": sum(r["ai_tier"] == r["expected"] for r in rows),
        "json_valid": sum(r["json_valid"] for r in rows),
        "spam_hit": spam_hit, "spam_pred": spam_pred, "spam_actual": spam_act,
        "hot_hit": hot_hit, "hot_pred": hot_pred, "hot_actual": hot_act,
        "confusion_final": confusion("final_tier"),
        "confusion_ai": confusion("ai_tier"),
        "llm_ms_p50": int(statistics.median(llm_ms)) if llm_ms else None,
        "llm_ms_p95": pct(llm_ms, 0.95) if llm_ms else None,
    }


# ---------------------------------------------------------------- invoice suite
def load_invoice_labels(slices: tuple[str, ...]) -> list[dict]:
    rows = []
    for folder in ("invoices", "invoices_alt"):
        path = DATA / folder / "labels.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    lab = json.loads(line)
                    lab["path"] = str(DATA / folder / lab["file"])
                    rows.append(lab)
    return [r for r in rows if r["split"] in slices]


async def run_invoice(label: dict, llm: Any, settings: Settings, prompt: str) -> dict:
    doc = pdf_text.read_pdf_text(Path(label["path"]).read_bytes(), settings.extract_max_pages_sync)
    want = label["data"]
    row = {"file": label["file"], "slice": label["split"], "expected_status": label["expected_status"],
           "label_reconciles": "bad_totals" not in label["flags"]}  # fmt: skip
    started = time.perf_counter()
    try:
        out = await extract_invoice(doc.text, llm=llm, settings=settings, prompt_version=prompt)
        got = out.data.model_dump(mode="json") if out.data else None
        diffs = field_diffs(got, want)
        first_errors = out.extra.get("errors_before_repair") or []
        crit, other = wrong_done_split(out.status, diffs)
        row.update(
            status=out.status,
            exact=not diffs,
            diffs=diffs,
            field_correct={f: bool(got) and got.get(f) == want[f] for f in HEADER_FIELDS},
            line_tp=match_lines((got or {}).get("line_items") or [], want["line_items"]),
            line_pred=len((got or {}).get("line_items") or []),
            line_exp=len(want["line_items"]),
            reconciles=reconciles(got),
            first_call_invalid=any(e.get("code") == "schema_error" for e in first_errors),
            repair=bool(out.extra.get("repair_attempted")),
            confidence=out.confidence.overall,
            llm_ms=out.meta.latency_ms,
            tokens=out.meta.tokens,
            cost_usd=out.meta.cost_usd,
            critical_wrong_done=crit,
            other_wrong_done=other,
        )
    except LLMError as exc:  # the first call failed outright (no JSON object, timeout, ...)
        row.update(status="llm_error", exact=False, diffs=["no data"], field_correct={}, line_tp=0, line_pred=0,
                   line_exp=len(want["line_items"]), reconciles=None, first_call_invalid="JSON" in str(exc),
                   repair=False, confidence=0.0, llm_ms=None, tokens=0, cost_usd=None, critical_wrong_done=[],
                   other_wrong_done=[], error=str(exc))  # fmt: skip
    row["wall_ms"] = int((time.perf_counter() - started) * 1000)
    return row


# ---------------------------------------------------------------- lead suite
class LeadAssessment(BaseModel):
    """The AI step's output fields (the Zap's typed output fields; prompts/lead_icp_v1.md)."""

    fit_score: int = Field(ge=0, le=100)
    tier: Literal["hot", "warm", "cold", "spam"]
    intent_summary: str
    recommended_service: Literal["AI automation", "Zapier / n8n workflows", "CRM setup", "Marketing automation", "Not a fit"]
    reply_draft: str


def run_code_step(filename: str, input_data: dict) -> dict:
    """Run a Code by Zapier step exactly like leadrouter/tests/test_code_steps.py: input_data in, output out."""
    scope = {"input_data": input_data}
    exec(compile((LEADROUTER / "code" / filename).read_text(encoding="utf-8"), filename, "exec"), scope)  # noqa: S102 - our own file
    return scope["output"]


def as_zapier(value: Any) -> str:
    """Zapier passes every mapped value as text; booleans arrive as 'true'/'false'."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def lead_user_message(fields: dict, enrichment: dict) -> str:
    form = "\n".join(f"{k}: {fields.get(k, '')}" for k in ("name", "email", "company", "website", "budget", "service", "timeline", "message"))
    enr = "\n".join(f"{k}: {as_zapier(enrichment.get(k))}" for k in ("site_summary", "industry_guess", "size_band_guess", "is_free_mail", "rule_score"))
    return f"Lead form fields:\n{form}\n\nOpsCore enrichment:\n{enr}"


async def run_lead(lead: dict, llm: Any, settings: Settings, system: str) -> dict:
    fields = {**lead["fields"], "name": (lead["fields"].get("name") or "").title()}  # step 2 Formatter: title case
    prep = run_code_step("prepare_lead.py", fields)
    enr = lead["enrichment"]
    row = {"lead_ref": lead["lead_ref"], "slice": lead["slice"], "expected": lead["expected_tier"]}
    ai: dict = {}
    try:
        res = await llm.complete_json(system=system, user=lead_user_message(fields, enr), schema=LeadAssessment.model_json_schema(),
                                      tool_name="qualify_lead", model=settings.llm_model_fast, max_tokens=1024, timeout=90)  # fmt: skip
        row.update(llm_ms=res.latency_ms, tokens=res.input_tokens + res.output_tokens, cost_usd=res.cost_usd)
        try:
            ai = LeadAssessment.model_validate(res.data).model_dump()
            row["json_valid"] = True
        except ValidationError:
            row["json_valid"] = False
    except LLMError as exc:
        row.update(llm_ms=None, tokens=0, cost_usd=None, json_valid=False, error=str(exc))
    score = run_code_step("score_lead.py", {
        "base_score": as_zapier(prep.get("base_score")), "is_spam": as_zapier(prep.get("is_spam")),
        "spam_reasons": as_zapier(prep.get("spam_reasons")), "ops_is_disposable": as_zapier(enr.get("is_disposable")),
        "ops_industry": as_zapier(enr.get("industry_guess")), "ops_size": as_zapier(enr.get("size_band_guess")),
        "ai_fit_score": as_zapier(ai.get("fit_score")), "ai_tier": as_zapier(ai.get("tier")),
        "ai_recommended_service": as_zapier(ai.get("recommended_service")),
        "name": fields.get("name", ""), "company": fields.get("company", ""), "budget": fields.get("budget", ""), "service": fields.get("service", ""),
    })  # fmt: skip
    row.update(ai_tier=ai.get("tier"), fit_score=ai.get("fit_score"), base_score=prep.get("base_score"),
               final_score=score["final_score"], final_tier=score["tier"], score_source=score["score_source"])  # fmt: skip
    return row


# ---------------------------------------------------------------- running
def ollama_facts(settings: Settings, model: str) -> dict:
    if settings.llm_provider != "openai_compat" or not settings.llm_base_url:
        return {}
    root = settings.llm_base_url.rstrip("/").removesuffix("/v1")
    try:
        tags = httpx.get(f"{root}/api/tags", timeout=5).json().get("models", [])
        version = httpx.get(f"{root}/api/version", timeout=5).json().get("version")
    except (httpx.HTTPError, ValueError):
        return {}
    digest = next((m.get("digest", "")[:12] for m in tags if m.get("name") == model), None)
    return {"model_digest": digest, "ollama_version": version}


def build_settings(args: argparse.Namespace) -> Settings:
    base = Settings()
    update: dict[str, Any] = {"llm_seed": args.seed}
    if args.provider:
        update["llm_provider"] = args.provider
    if args.base_url is not None:
        update["llm_base_url"] = args.base_url or None
    if args.api_key_env:
        update["llm_api_key"] = SecretStr(os.environ.get(args.api_key_env, ""))
        update["llm_reasoning_effort"] = None
    if args.temperature is not None:
        update["llm_temperature"] = args.temperature
    if getattr(args, "json_mode", None):
        update["llm_json_mode"] = args.json_mode
    model = args.model or base.llm_model_extract
    update["llm_model_extract"] = model
    update["llm_model_fast"] = model
    return base.model_copy(update=update)


async def run_suite(args: argparse.Namespace) -> Path:
    settings = build_settings(args)
    model = settings.llm_model_extract
    facts = ollama_facts(settings, model) if args.mode != "replay" else {}
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{args.suite}_{args.tag}"
    cassette_path = Path(args.cassette) if args.cassette else CASSETTES / f"{run_id}.jsonl"
    key_settings = {"provider": settings.llm_provider, "model_digest": facts.get("model_digest"),
                    "temperature": settings.llm_temperature if settings.llm_provider == "anthropic" else 0,
                    "seed": settings.llm_seed if settings.llm_provider == "openai_compat" else None,
                    "json_mode": settings.llm_json_mode, "reasoning_effort": settings.llm_reasoning_effort}  # fmt: skip
    if args.mode == "replay":
        llm: Any = ReplayLLM(cassette_path)
        key_settings = llm.settings
        facts = {"model_digest": key_settings.get("model_digest")}
    elif args.mode == "record":
        llm = RecordingLLM(build_llm(settings), key_settings)
    else:
        llm = build_llm(settings)

    if args.mode != "replay":  # load the model first, so its load time doesn't land on the first document (not recorded)
        try:
            await build_llm(settings).complete_json(system="Health check.", user="Set ok to true.", tool_name="health_check",
                                                    schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                                                    model=model, max_tokens=64, timeout=300)  # fmt: skip
        except LLMError as exc:
            print(f"warm-up failed: {exc}")

    slices = tuple(args.slices.split(",")) if args.slices else (INVOICE_SLICES if args.suite == "invoices" else LEAD_SLICES)
    out: dict[str, Any] = {
        "run_id": run_id, "ran_at": datetime.now(UTC).isoformat(), "mode": args.mode, "suite": args.suite, "tag": args.tag,
        "config": {"prompt": args.prompt, "provider": settings.llm_provider, "model": model, "slices": list(slices),
                   "repeats": args.repeats, "seed": args.seed, "temperature": args.temperature,
                   "json_mode": settings.llm_json_mode, "reasoning_effort": settings.llm_reasoning_effort},
        "env": {**facts, "hardware": args.hardware, "key_settings": key_settings},
        "cassette": str(cassette_path) if args.mode in ("record", "replay") else None,
        "slices": {},
    }  # fmt: skip
    started = time.perf_counter()
    if args.suite == "invoices":
        labels = load_invoice_labels(slices)
        for name in slices:
            items = [lab for lab in labels if lab["split"] == name]
            reps = args.repeats if name.startswith("test") else 1
            out["slices"][name] = {"repeats": []}
            for rep in range(reps):
                rows = []
                for lab in items:
                    rows.append(await run_invoice(lab, llm, settings, args.prompt))
                    print(f"  {name} r{rep + 1} {lab['file']}: {rows[-1]['status']} exact={rows[-1]['exact']}", flush=True)
                out["slices"][name]["repeats"].append({"metrics": invoice_metrics(rows), "rows": rows})
    else:
        system = load_prompt(settings.prompts_dir, args.prompt)
        leads = [json.loads(line) for line in (DATA / "leads.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        for name in slices:
            items = [lead for lead in leads if lead["slice"] == name]
            reps = args.repeats if name == "leads_test" else 1
            out["slices"][name] = {"repeats": []}
            for rep in range(reps):
                rows = []
                for lead in items:
                    rows.append(await run_lead(lead, llm, settings, system))
                    print(f"  {name} r{rep + 1} {lead['lead_ref']}: exp {lead['expected_tier']} final {rows[-1]['final_tier']} ai {rows[-1]['ai_tier']}", flush=True)
                out["slices"][name]["repeats"].append({"metrics": lead_metrics(rows), "rows": rows})
    out["wall_s"] = round(time.perf_counter() - started, 1)

    if args.mode == "record":
        llm.save(cassette_path)
    if args.mode == "replay" and llm.unused():
        out["replay_unused_answers"] = llm.unused()
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = Path(args.out) if args.out else RESULTS / f"run_{run_id}.json"
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"saved {path}" + (f" and cassette {cassette_path}" if args.mode == "record" else ""))
    return path


# ---------------------------------------------------------------- gate
GATED_INVOICE = ("n", "field_accuracy", "per_field", "doc_exact", "status_ok", "line_tp", "line_pred", "line_exp", "reconciles",
                 "first_call_invalid", "llm_errors", "repairs", "wrong_done_docs", "critical_cases", "other_wrong_done",
                 "llm_ms_p50", "llm_ms_p95", "tokens_mean")  # fmt: skip
GATED_LEAD = ("n", "final_correct", "ai_correct", "json_valid", "confusion_final", "confusion_ai", "llm_ms_p50", "llm_ms_p95")
MAX_DROP_POINTS = 5.0


def accuracy_of(suite: str, m: dict) -> float:
    if suite == "invoices":
        return 100 * (m["field_accuracy"] or 0)
    return 100 * m["final_correct"] / m["n"] if m["n"] else 0.0


def gate(current: dict, baseline: dict, *, exact: bool) -> list[str]:
    """Problems found (empty = pass). exact=True for replay (identical answers must give identical scores)."""
    problems = []
    suite = current["suite"]
    keys = GATED_INVOICE if suite == "invoices" else GATED_LEAD
    for name, base_slice in baseline["slices"].items():
        cur_slice = current["slices"].get(name)
        if not cur_slice:
            problems.append(f"{name}: missing from this run")
            continue
        base_reps = [r["metrics"] for r in base_slice["repeats"]]
        cur_reps = [r["metrics"] for r in cur_slice["repeats"]]
        if exact:
            for i, (b, c) in enumerate(zip(base_reps, cur_reps)):
                for k in keys:
                    if b.get(k) != c.get(k):
                        problems.append(f"{name} run {i + 1}: {k} {c.get(k)!r} != baseline {b.get(k)!r}")
            if len(base_reps) != len(cur_reps):
                problems.append(f"{name}: {len(cur_reps)} runs != baseline {len(base_reps)}")
            continue
        base_acc = statistics.median(accuracy_of(suite, m) for m in base_reps)
        cur_acc = statistics.median(accuracy_of(suite, m) for m in cur_reps)
        if base_acc - cur_acc > MAX_DROP_POINTS:
            problems.append(f"{name}: accuracy {cur_acc:.1f} is {base_acc - cur_acc:.1f} points below baseline {base_acc:.1f} (limit {MAX_DROP_POINTS})")
        if suite == "invoices":
            if max(m["first_call_invalid"] for m in cur_reps) > max(m["first_call_invalid"] for m in base_reps):
                problems.append(f"{name}: more first-call invalid outputs than baseline")
            known = {tuple(c) for m in base_reps for c in m["critical_cases"]}
            new = sorted({tuple(c) for m in cur_reps for c in m["critical_cases"]} - known)
            if new:
                problems.append(f"{name}: new wrong money/number/invoice-number values reached done: {new}")
        else:
            if min(m["json_valid"] for m in cur_reps) < min(m["json_valid"] for m in base_reps):
                problems.append(f"{name}: fewer valid JSON answers than baseline")
    return problems


def summarise_run(result: dict) -> dict:
    """What baseline.json keeps per run: config, env, cassette and metrics (rows are dropped)."""
    return {k: result[k] for k in ("run_id", "suite", "tag", "config", "env", "cassette")} | {
        "slices": {name: {"repeats": [{"metrics": r["metrics"]} for r in s["repeats"]]} for name, s in result["slices"].items()}
    }


# ---------------------------------------------------------------- report
def frac(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "n/a"


def spread(values: list, fmt=str) -> str:
    """One value, or the median and min-max over repeated runs. Values are raw numbers; fmt formats them."""
    if len(values) == 1:
        return fmt(values[0])
    if all(v == values[0] for v in values):
        return f"{fmt(values[0])} (identical in {len(values)} runs)"
    ordered = sorted(values)
    return f"{fmt(statistics.median_low(values))} (range {fmt(ordered[0])} to {fmt(ordered[-1])}, {len(values)} runs)"


def table_row(result: dict, title: str, get, fmt) -> str:
    """get(metrics) -> raw number; fmt(value, metrics) -> text. One column per slice, spread over repeats."""
    cells = []
    for s in result["slices"].values():
        first = s["repeats"][0]["metrics"]
        cells.append(spread([get(r["metrics"]) for r in s["repeats"]], lambda v, m=first: fmt(v, m)))
    return f"| {title} | " + " | ".join(cells) + " |"


def seconds(ms) -> str:
    return "n/a" if ms is None else f"{ms / 1000:.1f} s"


def invoice_section(result: dict) -> list[str]:
    cfg = result["config"]
    lines = [f"### Invoices: `{cfg['prompt']}` on `{cfg['model']}` ({cfg['provider']})", "",
             f"Run `{result['run_id']}` ({result['mode']}); source: `{result.get('_path', '')}`.", "",
             "| Metric | " + " | ".join(f"{n} (n={s['repeats'][0]['metrics']['n']})" for n, s in result["slices"].items()) + " |",
             "|---|" + "---|" * len(result["slices"])]  # fmt: skip

    t = lambda title, get, fmt: table_row(result, title, get, fmt)  # noqa: E731
    lines += [
        t("Field accuracy (8 header fields)", lambda m: m["field_accuracy"], lambda v, m: f"{100 * v:.1f}%"),
        t("Documents fully exact", lambda m: m["doc_exact"], lambda v, m: frac(v, m["n"])),
        t("Status as expected", lambda m: m["status_ok"], lambda v, m: frac(v, m["n"])),
        t("Line items F1", lambda m: m["line_f1"], lambda v, m: f"{v:.3f}"),
        t("Totals reconcile", lambda m: m["reconciles"], lambda v, m: frac(v, m["reconciles_n"])),
        t("First-call invalid JSON/schema", lambda m: m["first_call_invalid"], lambda v, m: frac(v, m["n"])),
        t("Repair passes", lambda m: m["repairs"], lambda v, m: frac(v, m["n"])),
        t("Wrong data still `done`", lambda m: m["wrong_done_docs"], lambda v, m: frac(v, m["n"])),
        t("…of which money/number/invoice no. fields", lambda m: len(m["critical_cases"]), lambda v, m: str(v)),
        t("LLM time per doc, p50", lambda m: m["llm_ms_p50"], lambda v, m: seconds(v)),
        t("LLM time per doc, p95", lambda m: m["llm_ms_p95"], lambda v, m: seconds(v)),
        t("Tokens per doc (mean)", lambda m: m["tokens_mean"], lambda v, m: str(v)),
        t("Cost", lambda m: m["cost_usd_total"] or 0, lambda v, m: "$0 (local model)" if m["cost_usd_total"] is None
          else f"${v:.4f} for the slice, list-price estimate"),
    ]
    field_rows = ["", "Per-field accuracy (first run of each slice):", "",
                  "| Field | " + " | ".join(result["slices"]) + " |", "|---|" + "---|" * len(result["slices"])]
    for f in HEADER_FIELDS:
        field_rows.append(f"| {f} | " + " | ".join(frac(s["repeats"][0]["metrics"]["per_field"][f], s["repeats"][0]["metrics"]["n"]) for s in result["slices"].values()) + " |")
    lines += field_rows
    cases = sorted({(name, *c) for name, s in result["slices"].items() for r in s["repeats"] for c in r["metrics"]["critical_cases"]})
    lines += ["", "Wrong money/number/invoice-number values that reached `done`: " + (", ".join(f"{n}:{f}:{fld}" for n, f, fld in cases) if cases else "**none**.")]
    return lines


def lead_section(result: dict) -> list[str]:
    cfg = result["config"]
    lines = [f"### Leads: `{cfg['prompt']}` on `{cfg['model']}` + LeadRouter scoring code", "",
             f"Run `{result['run_id']}` ({result['mode']}); source: `{result.get('_path', '')}`.", "",
             "| Metric | " + " | ".join(f"{n} (n={s['repeats'][0]['metrics']['n']})" for n, s in result["slices"].items()) + " |",
             "|---|" + "---|" * len(result["slices"])]  # fmt: skip

    t = lambda title, get, fmt: table_row(result, title, get, fmt)  # noqa: E731
    lines += [
        t("Final tier correct (0.6 × AI + 0.4 × rules)", lambda m: m["final_correct"], lambda v, m: frac(v, m["n"])),
        t("AI tier alone correct", lambda m: m["ai_correct"], lambda v, m: frac(v, m["n"])),
        t("Spam precision", lambda m: m["spam_hit"], lambda v, m: frac(v, m["spam_pred"])),
        t("Spam recall", lambda m: m["spam_hit"], lambda v, m: frac(v, m["spam_actual"])),
        t("Hot precision", lambda m: m["hot_hit"], lambda v, m: frac(v, m["hot_pred"])),
        t("Valid JSON answers", lambda m: m["json_valid"], lambda v, m: frac(v, m["n"])),
        t("LLM time per lead, p50", lambda m: m["llm_ms_p50"], lambda v, m: seconds(v)),
        t("LLM time per lead, p95", lambda m: m["llm_ms_p95"], lambda v, m: seconds(v)),
    ]
    for name, s in result["slices"].items():
        conf = s["repeats"][0]["metrics"]["confusion_final"]
        lines += ["", f"Confusion, final tier, {name} (rows = label, columns = predicted; first run):", "",
                  "| label \\ predicted | hot | warm | cold | spam |", "|---|---|---|---|---|"]
        lines += [f"| {e} | " + " | ".join(str(conf[e][p]) for p in TIERS) + " |" for e in TIERS]
    return lines


def write_report(paths: list[Path], out: Path) -> None:
    results = []
    for p in paths:
        r = json.loads(p.read_text(encoding="utf-8"))
        r["_path"] = str(p).replace("\\", "/")
        results.append(r)
    env = next((r["env"] for r in results if r["env"].get("model_digest")), results[0]["env"] if results else {})
    lines = [
        "# OpsCore eval report",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `python -m evals.run_evals report` from the run files listed per section.",
        "Every number below comes from those runs; nothing is typed in by hand. Method, splits and gate: DECISIONS D29.",
        "",
        "**How to read this**",
        f"- Hardware: {env.get('hardware') or 'not recorded'}; Ollama {env.get('ollama_version') or '?'}; local model digest `{env.get('model_digest') or '?'}`. "
        "Latencies are model time on that machine. Local runs cost $0; hosted-API costs are list-price estimates from measured tokens.",
        "- Sampling: temperature 0 and a fixed seed. Test slices run several times; ranges show run-to-run spread.",
        "- Slices are never blended. `dev` (1-20) and `val` (21-40) were seen while writing prompts and choosing v2, so they are not "
        "unbiased. `test_same_template` (41-60) is new instances of the same 3 templates; `test_new_layout` (8) is a separately "
        "written template, the fairest generalisation check.",
        "- Small samples: one invoice is 5 points on n=20, 12.5 on n=8; one lead is about 7 points on n=14 or 6 on n=16.",
        "- Leads: Zapier's AI step uses Zapier's own model; these runs score the same prompt and LeadRouter's scoring code on the local model. "
        "`leads_dev` (14) was used while building LeadRouter. `leads_test` (16) was labelled by Claude from the written ideal-client rubric, at the owner's request, before any model run on it; the labeller also wrote the prompt, so neither lead slice is independent.",
        "",
    ]
    for r in results:
        lines += (invoice_section(r) if r["suite"] == "invoices" else lead_section(r)) + [""]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")


# ---------------------------------------------------------------- CLI
def add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--suite", choices=("invoices", "leads"), required=True)
    p.add_argument("--prompt", required=True, help="invoice_extract_v2, invoice_extract_v1 or lead_icp_v1")
    p.add_argument("--slices", help="comma-separated; default: all slices of the suite")
    p.add_argument("--repeats", type=int, default=1, help="repeats for test slices")
    p.add_argument("--mode", choices=("live", "record", "replay"), default="record")
    p.add_argument("--tag", default="run")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--temperature", type=float, default=None, help="Anthropic only; OpenAI-compatible calls use 0")
    p.add_argument("--provider", choices=("openai_compat", "anthropic"))
    p.add_argument("--model")
    p.add_argument("--base-url", dest="base_url")
    p.add_argument("--api-key-env", dest="api_key_env", help="name of the env var holding the API key (never the key itself)")
    p.add_argument("--hardware", default="", help='e.g. "NVIDIA GTX 1660 SUPER 6 GB"')
    p.add_argument("--json-mode", dest="json_mode", choices=("tool", "structured", "prompt"), help="override LLM_JSON_MODE (Anthropic: tool)")
    p.add_argument("--cassette", help="cassette path (record: where to save; replay: what to read)")
    p.add_argument("--out")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    add_run_args(sub.add_parser("run"))
    rep = sub.add_parser("report")
    rep.add_argument("results", nargs="+")
    rep.add_argument("--out", default="evals/report.md")
    base = sub.add_parser("baseline")
    base.add_argument("results", nargs="+")
    base.add_argument("--out", default="evals/baseline.json")
    gt = sub.add_parser("gate")
    gt.add_argument("--baseline", default="evals/baseline.json")
    gt.add_argument("--exact", action="store_true", help="replay mode: scores must equal the baseline")
    gt.add_argument("results", nargs="+")
    ci = sub.add_parser("ci")
    ci.add_argument("--baseline", default="evals/baseline.json")
    ci.add_argument("--report-out", default="evals/report_ci.md")
    args = parser.parse_args()

    if args.cmd == "run":
        asyncio.run(run_suite(args))
        return 0
    if args.cmd == "report":
        write_report([Path(p) for p in args.results], Path(args.out))
        return 0
    if args.cmd == "baseline":
        runs = [summarise_run(json.loads(Path(p).read_text(encoding="utf-8"))) for p in args.results]
        Path(args.out).write_text(json.dumps({"written_at": datetime.now(UTC).isoformat(), "max_drop_points": MAX_DROP_POINTS, "runs": runs}, indent=1), encoding="utf-8")
        print(f"wrote {args.out} with {len(runs)} runs")
        return 0
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    by_id = {r["run_id"]: r for r in baseline["runs"]}
    if args.cmd == "gate":
        problems = []
        for p in args.results:
            cur = json.loads(Path(p).read_text(encoding="utf-8"))
            ref = next((r for r in baseline["runs"] if r["suite"] == cur["suite"] and r["config"]["prompt"] == cur["config"]["prompt"]
                        and r["config"]["model"] == cur["config"]["model"]), None)  # fmt: skip
            if ref is None:
                problems.append(f"{p}: no baseline run for {cur['suite']}/{cur['config']['prompt']}/{cur['config']['model']}")
                continue
            problems += [f"{cur['run_id']}: {msg}" for msg in gate(cur, ref, exact=args.exact)]
        print("GATE PASS" if not problems else "GATE FAIL\n  " + "\n  ".join(problems))
        return 0 if not problems else 1
    # ci: replay every baseline run from its cassette, gate exactly, write a report
    problems, paths = [], []
    for run_id, ref in by_id.items():
        ns = argparse.Namespace(suite=ref["suite"], prompt=ref["config"]["prompt"], slices=",".join(ref["config"]["slices"]),
                                repeats=ref["config"]["repeats"], mode="replay", tag=f"ci_{ref['tag']}", seed=ref["config"]["seed"],
                                temperature=ref["config"]["temperature"], provider=ref["config"]["provider"], model=ref["config"]["model"],
                                json_mode=ref["config"].get("json_mode"),
                                base_url=None, api_key_env=None, hardware=ref["env"].get("hardware", ""), cassette=ref["cassette"],
                                out=str(RESULTS / f"ci_{run_id}.json"))  # fmt: skip
        try:
            path = asyncio.run(run_suite(ns))
        except CassetteMiss as exc:
            problems.append(f"{run_id}: {exc}")
            continue
        paths.append(path)
        cur = json.loads(path.read_text(encoding="utf-8"))
        problems += [f"{run_id}: {msg}" for msg in gate(cur, ref, exact=True)]
        if cur.get("replay_unused_answers"):
            problems.append(f"{run_id}: {cur['replay_unused_answers']} recorded answers were never used")
    if paths:
        write_report(paths, Path(args.report_out))
    print("CI EVAL GATE PASS" if not problems else "CI EVAL GATE FAIL\n  " + "\n  ".join(problems))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
