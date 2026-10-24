"""End-to-end /v1/leads/enrich latency against the running API (real DNS, real homepage fetch, real LLM).

Each domain is called once with a fresh Idempotency-Key, so the numbers include everything a Zap
would wait for. The first call per domain is a cache miss; `cached` is reported so repeats are visible.
Usage (inside the api container):  python -m evals.bench_enrich_e2e
"""

import json
import statistics
import time
import uuid
from pathlib import Path

import httpx

from evals.bench_llm import DEFAULT_SITES

KEY = Path("/app/.secrets/dev.key").read_text(encoding="utf-8").strip()


def main() -> None:
    rows = []
    with httpx.Client(base_url="http://localhost:8000", timeout=30) as client:
        for site in DEFAULT_SITES:
            domain = site.split("://", 1)[1]
            started = time.perf_counter()
            r = client.post(
                "/v1/leads/enrich",
                headers={"X-API-Key": KEY, "Idempotency-Key": f"bench-{uuid.uuid4().hex[:12]}"},
                json={"email": f"test.lead@{domain}", "website": site},
            )
            ms = int((time.perf_counter() - started) * 1000)
            body = r.json()
            rows.append({"domain": domain, "ms": ms, "status": r.status_code, **{k: body.get(k) for k in ("cached", "industry_guess", "size_band_guess", "rule_score", "note")}})
            print(f"{domain:<22} {ms:>6} ms  cached={body.get('cached')!s:<5} industry={body.get('industry_guess')!s:<32} note={body.get('note')}")
    fresh = [r["ms"] for r in rows if not r["cached"]]
    filled = sum(1 for r in rows if r["industry_guess"])
    print(f"\n{len(rows)} calls | industry filled: {filled}/{len(rows)} | uncached p50 {int(statistics.median(fresh)) if fresh else '-'} ms, max {max(fresh) if fresh else '-'} ms"
          f" | under 5 s: {sum(1 for r in rows if r['ms'] < 5000)}/{len(rows)}")  # fmt: skip
    Path("evals/results").mkdir(parents=True, exist_ok=True)
    Path(f"evals/results/bench_enrich_e2e_{time.strftime('%Y%m%dT%H%M%S')}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
