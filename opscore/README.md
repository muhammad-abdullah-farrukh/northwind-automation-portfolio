# OpsCore

The Python engine behind Northwind Digital's automations. The no-code flows decide *what happens*
(Zapier **LeadRouter**, n8n **InvoiceIQ**); OpsCore decides *what the data is*: lead enrichment,
and invoice extraction with validation, a repair pass, confidence, duplicate checks, async jobs with
HMAC-signed callbacks, and an eval harness that gates CI.

**Stack:** Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 + Alembic · PostgreSQL 16 + pgvector ·
Redis · Celery · httpx · Anthropic / OpenAI-compatible SDKs · pytest · Docker Compose · Cloudflare quick tunnel

## Quickstart

Prerequisite: Docker Desktop.

```bash
cp .env.example .env            # then fill in POSTGRES_PASSWORD and the LLM_* settings
docker compose up -d --build    # postgres, redis, migrate, api, worker, cloudflared
docker compose exec api python -m app.cli create-key --name dev   # key written to .secrets/dev.key
docker compose exec api pytest
```

- Swagger UI: http://127.0.0.1:8000/docs
- Public URL (for Zapier): `docker compose logs cloudflared | grep trycloudflare`. The quick-tunnel URL changes every time the container restarts.
- Smoke test (Windows): `powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1`

## Endpoints

| Endpoint | Auth | What it does |
|---|---|---|
| `GET /healthz` | none | DB + Redis reachability. 503 if either is down. |
| `POST /v1/leads/enrich` | `X-API-Key` | Sync, time-boxed by `ENRICH_BUDGET_S` (9 s on the local-GPU setup, DECISIONS D18). Checks email syntax and MX, flags free-mail and disposable domains, fetches the homepage safely, gets an LLM site summary, industry and size guess, and computes a rule score. Cached per domain for 30 days. Optional `Idempotency-Key`. |
| `POST /v1/extract/sync` | `X-API-Key` | Multipart `file` (PDF, up to 5 pages, 10 MB) + `schema=invoice`. Runs text layer → schema-constrained LLM extraction → validation → one repair pass → confidence → duplicate check. Returns `done` / `needs_review` / `failed`. Optional `Idempotency-Key`. |
| `POST /v1/jobs` | `X-API-Key` | Async version: `202` + `job_id`; a Celery worker extracts and POSTs the signed result to `callback_url`. The same key or PDF returns the same `job_id`. |
| `GET /v1/jobs`, `GET /v1/jobs/{id}` | `X-API-Key` | Review queue (`?status=needs_review`) and the job's status and result. |
| `GET /v1/jobs/{id}/export` | `X-API-Key` | `?format=xlsx` or `csv` export of an extracted invoice. |
| `POST /v1/jobs/{id}/review` | `X-API-Key` | Stores a human correction; it becomes eval ground truth. |

```bash
curl -s https://<tunnel>.trycloudflare.com/v1/leads/enrich \
  -H "X-API-Key: $OPSCORE_KEY" -H "Idempotency-Key: $(echo -n jane@acme.io | sha256sum | cut -c1-64)" \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@acme.io","website":"acme.io","company":"Acme","name":"Jane Doe"}'
```

Response contract (LeadRouter depends on these exact fields, in this order):

```json
{"email":"jane@acme.io","domain":"acme.io","mx_valid":true,"is_free_mail":false,"is_disposable":false,
 "website_reachable":true,"site_summary":"...","industry_guess":"...","size_band_guess":"11-50",
 "rule_score":62,"enrich_confidence":0.78,"cached":false,"note":"industry and size are LLM guesses"}
```

**Behaviour:**
- **Degrades, never breaks.** If DNS, the site or the LLM is slow or down, you still get the full contract. The affected fields come back `null`, and `note` says what happened.
- **Invalid emails** are a `422`.
- **Idempotency.** Replaying an `Idempotency-Key` returns the stored response byte-for-byte, with `Idempotent-Replay: true`. The same key with a different body is a `409`.
- **Rate limit.** Each API key has its own per-minute limit, and exceeding it returns a `429` with a `Retry-After` header.

### Async jobs (P4)

```bash
# queue a PDF; the signed result is POSTed to callback_url when done (202 + job_id; same PDF again -> same job_id)
curl -s http://127.0.0.1:8000/v1/jobs -H "X-API-Key: $OPSCORE_KEY"   -F "file=@evals/data/invoices/inv_001.pdf;type=application/pdf" -F "schema=invoice"   -F "callback_url=https://hooks.example.com/opscore"
curl -s http://127.0.0.1:8000/v1/jobs/<job_id>              -H "X-API-Key: $OPSCORE_KEY"   # status + brief §4.4 contract
curl -s "http://127.0.0.1:8000/v1/jobs?status=needs_review" -H "X-API-Key: $OPSCORE_KEY"   # review queue
curl -s "http://127.0.0.1:8000/v1/jobs/<job_id>/export?format=xlsx" -H "X-API-Key: $OPSCORE_KEY" -o invoice.xlsx
curl -s http://127.0.0.1:8000/v1/jobs/<job_id>/review -H "X-API-Key: $OPSCORE_KEY" -H "Content-Type: application/json"   -d '{"data": {...corrected invoice...}, "notes": "fixed vendor name"}'
```

**Retries and callbacks:**
- **Retries:** up to 3 attempts, with exponential backoff and equal jitter (D25).
- **Callbacks:**
  - each callback carries `X-OpsCore-Signature: sha256=HMAC(secret, "<timestamp>.<raw body>")` and `X-OpsCore-Timestamp`;
  - every delivery attempt is logged in `webhook_deliveries`;
  - non-public callback hosts must be listed in `CALLBACK_HOST_MAP`, and TLS to them is verified against `CALLBACK_CA_FILE` (D26).

**Evidence from real runs:** `docs/evidence/`.

### Invoice extraction

```bash
curl -s http://127.0.0.1:8000/v1/extract/sync -H "X-API-Key: $OPSCORE_KEY" \
  -F "file=@evals/data/invoices/inv_001.pdf;type=application/pdf" -F "schema=invoice"
```

The response follows the contract in brief §4.4:

```json
{"job_id":"job_01J...","status":"done","duplicate_of":null,
 "data":{"vendor":"...","invoice_no":"...","invoice_date":"YYYY-MM-DD","due_date":"YYYY-MM-DD","currency":"GBP",
         "subtotal":0.0,"tax":0.0,"total":0.0,"line_items":[{"description":"...","qty":1.0,"unit_price":0.0,"amount":0.0}]},
 "confidence":{"overall":0.0,"fields":{"vendor":0.0,"total":0.0}},
 "validation":{"ok":true,"errors":[]},
 "meta":{"model":"...","prompt_version":"invoice_extract_v2","tokens":0,"cost_usd":null,"latency_ms":0}}
```

The status tells n8n where to route the invoice:

| Status | Meaning |
|---|---|
| `done` | All checks passed and overall confidence is at least 0.85 |
| `needs_review` | A check failed after the repair pass, or confidence is below 0.85 |
| `failed` | No usable data (no text layer, or output still unparseable after repair) |

If the LLM is down, the endpoint returns `503` with `Retry-After`.

A non-null `duplicate_of` means the same vendor, invoice number and total were already extracted.

**Synthetic test data.** Every vendor is fictional, and the generator is deterministic:

```bash
docker compose exec api python -m evals.generate_invoices --count 5   # evals/data/invoices/*.pdf + labels.jsonl
powershell -ExecutionPolicy Bypass -File scripts\extract_samples.ps1   # posts each PDF and compares it with its label
```

## Local LLM (Ollama)

The default setup runs the model locally, on the GPU, through the `ollama` compose service (see DECISIONS D17):

| Setting | Value |
|---|---|
| Model | `qwen3:4b-instruct-2507-q4_K_M`, 3.2 GB in VRAM, 100% GPU on a GTX 1660 SUPER (6 GB) |
| Endpoint | OpenAI-compatible: `LLM_PROVIDER=openai_compat`, `LLM_BASE_URL=http://ollama:11434/v1` |
| JSON | `LLM_JSON_MODE=structured` (JSON-schema response format), temperature 0 |
| Thinking | `LLM_REASONING_EFFORT=none` switches off hidden reasoning on thinking models |
| Prompts | `invoice_extract_v2` and `site_enrich_v3`, chosen on held-out runs (D22, D23) |

```bash
docker compose exec ollama ollama pull qwen3:4b-instruct-2507-q4_K_M   # about 2.5 GB, once
docker compose exec api python -m app.cli llm-ping                     # first call loads the model; it then stays in VRAM
docker compose exec api python -m evals.bench_llm --models qwen3:4b-instruct-2507-q4_K_M --invoices 21-40 --skip-enrich
```

Benchmark results are saved under `evals/results/`. Any number quoted in these docs comes from one of those files.

## Evals

**Scorecard:** [`evals/report.md`](evals/report.md). **Method and gate:** DECISIONS [D29](DECISIONS.md). **Findings:** [D30](DECISIONS.md).
- **Setup.** Everything runs through production code: `extract_invoice` and LeadRouter's own Code steps. Sampling is fixed (temperature 0, seed 42), and the test slices run 3 times.
- **Invoice slices (never blended):**
  - `dev` (1–20) and `val` (21–40) were seen while building the prompts;
  - `test_same_template` (41–60) is new invoices from the same 3 templates;
  - `test_new_layout` (8) comes from an independently written template.
- **Lead slices:** 14 dev and 16 test leads. Both are labelled from the written rubric, so they are not independent.

Headline numbers, production prompt `invoice_extract_v2` on local qwen3 4B (GTX 1660 SUPER, $0 per document):

| | test_same_template (n=20) | test_new_layout (n=8) |
|---|---|---|
| Field accuracy, 8 header fields | 93.1% | 98.4% |
| Documents fully exact | 15/20 | 5/8 |
| Line-item F1 | 0.945 | 0.842 |
| Wrong amount / quantity / invoice no. that still reached `done` | **0** | **0** |
| Model time per document, p50 | 6.6 s | 13.9 s |

All three repeat runs gave identical scores. The misses on the new layout (amounts like `1 754,49` read as `754.49`) were all caught by validation and sent to review. Leads: final tier correct 11/14 (dev) and 10/16 (test), spam recall 5/5, and over-scoring of warm leads is the main gap. See the report for every slice, the v1 comparison and the confusion matrices.

```bash
docker compose exec api python -m evals.generate_invoices --count 60      # dev/val/test_same_template (tests never printed)
docker compose exec api python -m evals.generate_invoices_alt             # test_new_layout
docker compose exec api python -m evals.build_leads                       # 30 leads with frozen enrichment
docker compose exec api python -m evals.run_evals run --suite invoices --prompt invoice_extract_v2 --repeats 3 --mode record --tag v2
docker compose exec api python -m evals.run_evals run --suite leads --prompt lead_icp_v1 --repeats 3 --mode record --tag leads
docker compose exec api python -m evals.run_evals report evals/results/run_*.json --out evals/report.md
docker compose exec api python -m evals.run_evals baseline evals/results/run_*.json --out evals/baseline.json
docker compose exec api python -m evals.run_evals ci                       # what CI runs: replay + exact gate
```

**CI** (`../.github/workflows/ci.yml`) runs pytest, the LeadRouter Code-step tests, and `run_evals ci`. That last step replays the recorded model answers in `evals/cassettes/`, so it needs no GPU and no API key. It fails if any score moves, or if a prompt or model changed without a re-recorded live run. Local proof: `docs/evidence/p6_ci_local.txt`.

## Configuration

All settings come from `.env` (see `.env.example`). The ones that matter:

| Variable | Meaning |
|---|---|
| `LLM_PROVIDER` | `anthropic` (the Anthropic API, or an Anthropic-compatible gateway via `LLM_BASE_URL`), `openai_compat` (Ollama, vLLM, ...), or `none` |
| `LLM_BASE_URL`, `LLM_API_KEY` | Endpoint and key |
| `LLM_MODEL_FAST`, `LLM_MODEL_EXTRACT` | Model for enrichment and model for invoice extraction |
| `LLM_JSON_MODE` | `tool` (forced tool call, the most portable), `structured` (`output_config` JSON schema) or `prompt` |
| `ENRICH_BUDGET_S` | Total time budget for `/v1/leads/enrich` |
| `LLM_SEED`, `LLM_TEMPERATURE` | Optional eval reproducibility: seed for OpenAI-compatible providers, temperature override for Anthropic. Unset in production. |

Admin CLI: `python -m app.cli create-key | list-keys | llm-ping [--list-models]`. The CLI never prints secrets.

## Layout

```
app/api/        HTTP routes (health, leads, extract, jobs)
app/core/       config, auth + rate limit, idempotency, JSON logging, ids, shared resources
app/services/   enrich, safe_fetch (SSRF guard), email checks, scoring, llm, pricing,
                pdf_text, extract, validate (+ grounding), repair, dedupe
app/models/     SQLAlchemy tables, Pydantic contracts (leads, invoice)
app/workers/    Celery app: async extraction jobs and signed callbacks
evals/          generators, labelled data, run_evals harness, cassettes, baseline, report.md
prompts/        versioned LLM prompts
alembic/        migrations
tests/          pytest (runs in the api container against a separate test database)
```

See [DECISIONS.md](DECISIONS.md) for the reasoning behind the design.
