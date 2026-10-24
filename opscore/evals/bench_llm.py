"""Benchmark candidate LLMs on OpsCore's two real jobs, using the production code paths.

1. Enrichment: the site_enrich_v1 prompt on real homepage text (fetched once, shared by all models).
   Measures LLM latency and whether the output passes the SiteGuess schema.
2. Extraction: the full extract_invoice pipeline (incl. repair pass) on the labelled sample invoices.
   Measures exact-match vs labels, status vs expected status, latency and tokens.

Every number printed or saved comes from this run. Usage (inside the api container):
    python -m evals.bench_llm --models granite4.2:3b,qwen2.5:3b
"""

import argparse
import asyncio
import json
import re
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.core.config import Settings
from app.models.schemas import SiteGuess
from app.services import pdf_text, safe_fetch
from app.services.scoring import size_band_for
from app.services.enrich import PROMPT_VERSION as SITE_PROMPT
from app.services.enrich import load_prompt
from app.services.extract import PROMPT_VERSION as EXTRACT_PROMPT
from app.services.extract import extract_invoice
from app.services.llm import LLMError, build_llm

# The company websites used by leadrouter/test_leads.json, so one run also vets the test-lead domains.
DEFAULT_SITES = [
    "https://buffer.com",
    "https://ghost.org",
    "https://plausible.io",
    "https://transistor.fm",
    "https://kit.com",
    "https://usefathom.com",
    "https://simpleanalytics.com",
    "https://buttondown.com",
    "https://basecamp.com",
    "https://python.org",
]
INVOICE_DIR = Path("evals/data/invoices")
RESULTS_DIR = Path("evals/results")


def field_diffs(got: dict | None, want: dict) -> list[str]:
    """Which fields differ from the label, e.g. ['invoice_date', 'line_items[1].qty: 3.5 != 3']."""
    if got is None:
        return ["no data"]
    diffs = []
    for key, expected in want.items():
        if key == "line_items":
            items = got.get("line_items") or []
            if len(items) != len(expected):
                diffs.append(f"line_items: {len(items)} lines != {len(expected)}")
                continue
            for i, (g, w) in enumerate(zip(items, expected)):
                diffs += [f"line_items[{i}].{k}: {g.get(k)!r} != {w[k]!r}" for k in w if g.get(k) != w[k]]
        elif got.get(key) != expected:
            diffs.append(f"{key}: {got.get(key)!r} != {expected!r}")
    return diffs


DEV_SPLIT_MAX_INDEX = 5  # invoices 1-5 were inspected while writing prompts and the confidence fix


def split_summary(rows: list[dict]) -> dict:
    """Exact-match / status / per-field error tally for one split. Field names drop list indexes."""
    tally: dict[str, int] = {}
    for row in rows:
        for diff in row.get("diffs") or []:
            name = re.sub(r"\[\d+\]", "", diff.split(":", 1)[0])
            tally[name] = tally.get(name, 0) + 1
    ms = [r["ms"] for r in rows]
    return {
        "docs": len(rows),
        "exact_match": sum(r["exact"] for r in rows),
        "status_as_expected": sum(r.get("status") == r["expected"] for r in rows),
        "repairs": sum(bool(r.get("repair")) for r in rows),
        "ms_p50": int(statistics.median(ms)) if ms else None,
        "ms_max": max(ms) if ms else None,
        "field_errors": dict(sorted(tally.items(), key=lambda kv: -kv[1])),
    }


def pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p * (len(ordered) - 1)))]


async def fetch_sites(sites: list[str], settings: Settings) -> list[tuple[str, str, int]]:
    pages = []
    for url in sites:
        started = time.perf_counter()
        try:
            res = await safe_fetch.fetch_homepage(url, timeout=5, max_bytes=settings.fetch_max_bytes)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {url}: {type(exc).__name__}")
            continue
        fetch_ms = int((time.perf_counter() - started) * 1000)
        text = safe_fetch.extract_page_text(res.text, settings.page_text_max_chars)
        if res.status_code >= 400 or len(text) < 500:
            print(f"  skip {url}: HTTP {res.status_code}, {len(text)} chars of text")
            continue
        pages.append((url, text, fetch_ms))
    return pages


async def bench_model(
    model: str,
    pages: list[tuple[str, str, int]],
    base: Settings,
    *,
    skip_extract: bool = False,
    site_prompt: str = SITE_PROMPT,
    extract_prompt: str = EXTRACT_PROMPT,
    invoice_range: tuple[int, int] | None = None,
) -> dict:
    settings = base.model_copy(update={"llm_model_fast": model, "llm_model_extract": model})
    llm = build_llm(settings)

    started = time.perf_counter()
    try:
        await llm.complete_json(system="Health check.", user="Set ok to true.", schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                                tool_name="health_check", model=model, max_tokens=512, timeout=180)  # fmt: skip
    except LLMError as exc:
        print(f"  warm-up for {model} failed: {exc}")
    load_ms = int((time.perf_counter() - started) * 1000)

    site_rows = []
    system = load_prompt(settings.prompts_dir, site_prompt)
    for url, text, fetch_ms in pages:
        user = f"Company name from the form: not given\nWebsite: {url}\n\n<homepage_text>\n{text}\n</homepage_text>"
        row = {"url": url, "fetch_ms": fetch_ms}
        try:
            res = await llm.complete_json(system=system, user=user, schema=SiteGuess.model_json_schema(), tool_name="record_site_guess",
                                          model=model, max_tokens=1024, timeout=60)  # fmt: skip
            row["llm_ms"] = res.latency_ms
            row["tokens"] = res.input_tokens + res.output_tokens
            try:
                guess = SiteGuess.model_validate(res.data)
                row.update(valid=True, industry=guess.industry_guess, size=size_band_for(guess.employee_count_stated) if site_prompt >= "site_enrich_v3" else res.data.get("size_band_guess"))
            except ValidationError as exc:
                row.update(valid=False, error=f"{exc.error_count()} schema errors")
        except LLMError as exc:
            row.update(valid=False, error=str(exc))
        site_rows.append(row)

    labels = [] if skip_extract else [json.loads(line) for line in (INVOICE_DIR / "labels.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if invoice_range:
        labels = [lab for lab in labels if invoice_range[0] <= lab["index"] <= invoice_range[1]]
    inv_rows = []
    for label in labels:
        doc = pdf_text.read_pdf_text((INVOICE_DIR / label["file"]).read_bytes(), settings.extract_max_pages_sync)
        started = time.perf_counter()
        row = {"file": label["file"], "index": label["index"], "expected": label["expected_status"]}
        try:
            out = await extract_invoice(doc.text, llm=llm, settings=settings, prompt_version=extract_prompt)
            diffs = field_diffs(out.data.model_dump(mode="json") if out.data else None, label["data"])
            row.update(
                status=out.status,
                exact=not diffs,
                diffs=diffs,
                confidence=out.confidence.overall,
                errors=[e.code for e in out.validation.errors],
                repair=out.extra.get("repair_attempted", False),
                tokens=out.meta.tokens,
            )
        except LLMError as exc:
            row.update(status="llm_error", exact=False, errors=[str(exc)])
        row["ms"] = int((time.perf_counter() - started) * 1000)
        inv_rows.append(row)

    llm_ms = [r["llm_ms"] for r in site_rows if "llm_ms" in r]
    e2e_ms = [r["llm_ms"] + r["fetch_ms"] for r in site_rows if "llm_ms" in r]
    return {
        "model": model,
        "load_ms": load_ms,
        "enrich": {
            "sites": len(site_rows),
            "valid": sum(r.get("valid", False) for r in site_rows),
            "llm_ms_p50": int(statistics.median(llm_ms)) if llm_ms else None,
            "llm_ms_max": max(llm_ms) if llm_ms else None,
            "fetch_plus_llm_ms_p95": pct(e2e_ms, 0.95) if e2e_ms else None,
            "rows": site_rows,
        },
        "extract": {
            "docs": len(inv_rows),
            "exact_match": sum(r["exact"] for r in inv_rows),
            "status_as_expected": sum(r.get("status") == r["expected"] for r in inv_rows),
            "ms_p50": int(statistics.median(r["ms"] for r in inv_rows)) if inv_rows else None,
            "dev": split_summary([r for r in inv_rows if r["index"] <= DEV_SPLIT_MAX_INDEX]),
            "held_out": split_summary([r for r in inv_rows if r["index"] > DEV_SPLIT_MAX_INDEX]),
            "rows": inv_rows,
        },
    }


def print_report(results: list[dict]) -> None:
    for r in results:
        e, x = r["enrich"], r["extract"]
        print(f"\n=== {r['model']}  (first call incl. load: {r['load_ms']} ms)")
        if e["sites"]:
            print(f"enrich : {e['valid']}/{e['sites']} valid | LLM p50 {e['llm_ms_p50']} ms, max {e['llm_ms_max']} ms | fetch+LLM p95 {e['fetch_plus_llm_ms_p95']} ms")
        for row in e["rows"]:
            detail = f"{row.get('industry')} / {row.get('size')}" if row.get("valid") else row.get("error")
            print(f"   {row['url']:<30} llm {row.get('llm_ms', '-'):>6} ms  {detail}")
        print(f"extract: {x['exact_match']}/{x['docs']} exact | {x['status_as_expected']}/{x['docs']} expected status | p50 {x['ms_p50']} ms per doc")
        for split in ("dev", "held_out"):
            sm = x.get(split) or {}
            if sm.get("docs"):
                print(f"  {split:<8} {sm['exact_match']}/{sm['docs']} exact | {sm['status_as_expected']}/{sm['docs']} expected status | "
                      f"{sm['repairs']} repaired | p50 {sm['ms_p50']} ms, max {sm['ms_max']} ms | field errors {sm['field_errors'] or 'none'}")  # fmt: skip
        for row in x["rows"]:
            print(f"   {row['file']} {row.get('status'):<13} exp {row['expected']:<13} exact={row['exact']!s:<5} conf={row.get('confidence')} repair={row.get('repair')} {row['ms']} ms {','.join(row.get('errors') or [])}")
            for diff in row.get("diffs") or []:
                print(f"        diff  {diff}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", required=True, help="comma-separated model names")
    parser.add_argument("--sites", default=",".join(DEFAULT_SITES))
    parser.add_argument("--page-chars", type=int, help="override PAGE_TEXT_MAX_CHARS for the enrichment prompt")
    parser.add_argument("--skip-enrich", action="store_true")
    parser.add_argument("--site-prompt", default=SITE_PROMPT, help="enrichment prompt version, e.g. site_enrich_v2")
    parser.add_argument("--extract-prompt", default=EXTRACT_PROMPT, help="extraction prompt version, e.g. invoice_extract_v2")
    parser.add_argument("--invoices", help="index range to run, e.g. 21-40 (default: all labelled invoices)")
    parser.add_argument("--skip-extract", action="store_true")
    args = parser.parse_args()

    base = Settings()
    if args.page_chars:
        base = base.model_copy(update={"page_text_max_chars": args.page_chars})
    print(f"page_text_max_chars={base.page_text_max_chars}")
    print("fetching homepages once (shared by all models)...")
    pages = [] if args.skip_enrich else await fetch_sites([s for s in args.sites.split(",") if s], base)
    invoice_range = tuple(int(x) for x in args.invoices.split("-")) if args.invoices else None
    print(f"site prompt: {args.site_prompt} | extract prompt: {args.extract_prompt} | invoices: {args.invoices or 'all'}")
    results = [
        await bench_model(m.strip(), pages, base, skip_extract=args.skip_extract, site_prompt=args.site_prompt,
                          extract_prompt=args.extract_prompt, invoice_range=invoice_range)
        for m in args.models.split(",")
    ]  # fmt: skip
    print_report(results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"bench_llm_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    meta = {"ran_at": datetime.now(UTC).isoformat(), "provider": base.llm_provider, "base_url": base.llm_base_url,
            "page_text_max_chars": base.page_text_max_chars, "reasoning_effort": base.llm_reasoning_effort,
            "site_prompt": args.site_prompt, "extract_prompt": args.extract_prompt, "invoices": args.invoices}  # fmt: skip
    out.write_text(json.dumps({**meta, "results": results}, indent=2), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    asyncio.run(main())
