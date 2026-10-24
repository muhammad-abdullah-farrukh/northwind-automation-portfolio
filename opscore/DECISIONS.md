# Decisions

Short records of the choices that shaped OpsCore, and why. Newest last.

## D1. The LLM sits behind a provider-agnostic interface (2026-09-25)
`app/services/llm.py` exposes one call, `complete_json(system, user, schema, ...)`, with three backends:
- the Anthropic SDK (optionally pointed at an Anthropic-compatible gateway through `LLM_BASE_URL`),
- an OpenAI-compatible client (Ollama or vLLM),
- `none`.

Callers always validate the returned dict with Pydantic, so no backend is trusted to follow the schema.

**Why:** the build started on a free gateway (AgentRouter), and it failed in stages, as the table below shows. Swapping providers has to be a `.env` change, not a code change.

What we saw on 2026-09-25:

| Call | Result |
|---|---|
| OpenAI-compatible endpoint | 401 "unauthorized client detected" |
| Anthropic-compatible `models.list` | worked once, then 401 |
| Anthropic-compatible `messages` | 402 "Budget pool quota has been exhausted", then 400 "content-blocked" |

We stopped calling it rather than trying to work around the gateway's client and content checks. `LLM_PROVIDER=none` is the safe default until a provider is chosen.

## D2. JSON comes back through a forced tool call by default
`LLM_JSON_MODE=tool` sends `tool_choice: {type: "tool"}` with the target schema as the tool's `input_schema`. That's the pattern most Anthropic-compatible gateways pass through.

`structured` (`output_config.format`) is the stricter option on the first-party API. `prompt` is the last resort for backends without tool support, and the parser takes the first JSON object out of the text.

## D3. Enrichment degrades instead of failing
LeadRouter's paths need *some* answer within Zapier's step timeout. So `/v1/leads/enrich` returns the full contract whenever the email is syntactically valid. That covers:
- the site is unreachable, blocked, or returns 4xx/5xx;
- the LLM times out, errors, or returns output that fails validation;
- the MX lookup times out.

In those cases the affected fields are `null`, and `note` names the cause. Only a syntactically invalid email returns an error (422), which also gives the Zap's error path a deterministic trigger.

The whole call runs inside `ENRICH_BUDGET_S` (4.8 s). The MX lookup runs in parallel with the site fetch, and the LLM gets whatever time is left, skipped if that's under 0.5 s.

## D4. MX timeout is "unknown", not "no MX"
The first smoke run reported `mx_valid: false` for a domain that has MX records. Its cold lookup through Docker's DNS took longer than the 1.5 s timeout.

`check_mx` now returns `None` on timeout, the API reports `false` with the note `mx lookup timed out`, and the timeout is 3 s. That's safe, because the lookup runs in parallel with the site fetch.

## D5. The site analysis is cached in Postgres for 30 days, and only when complete
The cache key is the site's host without `www.`. Postgres over a Redis TTL, for three reasons:
- the cache survives restarts;
- we can query it;
- it can later seed the lead eval set.

Degraded results are **not** cached, so one flaky run can't pin nulls on a domain for a month. MX is re-checked on every call, since it's cheap and per-address.

## D6. Idempotency works like Stripe's, scoped to (API key, endpoint, key)
The first request claims the key with an `in_progress` row (`INSERT ... ON CONFLICT DO NOTHING`), runs, then stores the status and body.

| Situation | Response |
|---|---|
| Same key, same body, completed | Stored response, byte-identical, with `Idempotent-Replay: true` |
| Same key, different body | 409 |
| Same key while the first request is still running | 409 |
| First request failed with a deterministic 4xx | Stored and replayed |
| First request failed with a 5xx or a crash | Key released, so the client can retry |

The header is optional: without it the request just runs. The stored body uses Postgres `json`, not `jsonb`. `jsonb` reorders keys, and the first smoke run caught replays coming back in a different field order (fixed in migration 0002).

## D7. The SSRF guard is on the homepage fetch
`/v1/leads/enrich` fetches URLs that strangers type into a web form, and the service is publicly reachable through the tunnel. So `safe_fetch`:
- allows only http/https on ports 80/443, with no credentials in the URL;
- resolves DNS itself and requires **every** address to be globally routable, which blocks loopback, RFC 1918, link-local/metadata (169.254.169.254), CGNAT, ULA and IPv4-mapped loopback;
- connects to the vetted IP, with the real hostname in the Host header and TLS SNI, so DNS can't change between the check and the connection;
- re-checks every redirect (at most 3);
- accepts HTML only, caps the body at 512 KB and times out at 2.5 s.

The page text goes to the LLM wrapped in `<homepage_text>` tags, and the prompt tells the model to treat it as untrusted data.

## D8. Scoring is deterministic and documented
Everything is capped to the 0–100 range.

**`rule_score`:**

| Signal | Points |
|---|---|
| MX valid | +20 |
| Not free-mail | +20 |
| Not disposable | +10 |
| Website reachable | +15 |
| Industry known | +10 |
| Industry matches an ICP keyword (SaaS, e-commerce, logistics, fintech, health, ...) | +10 |
| Size band | 11–50 or 51–200 +15; 201–1000 +10; 1–10 or 1000+ +5 |

A disposable address caps the total at 5. Budget and timeline aren't part of this score; LeadRouter's own `base_score` covers those.

**`enrich_confidence`:**
- 0 if the site wasn't reachable.
- Otherwise `0.5 × evidence coverage + 0.5 × the model's self-reported confidence`. Coverage counts five signals: reachable, at least 500 chars of text, LLM ok, industry known, size known.

## D9. API keys
- **Format:** `oc_` followed by 256 bits from `secrets.token_urlsafe`.
- **Storage:** only the SHA-256 hash is stored. Random keys don't need a slow hash.
- **Delivery:** `create-key` writes the key to git-ignored `.secrets/<name>.key` and prints only a prefix, so keys never appear in terminal output or logs.
- **Rate limit:** each key has its own fixed one-minute window in Redis.

## D10. Local exposure is minimal
Postgres (5433) and the API (8000) bind to `127.0.0.1` only. The n8n container still reaches the API at `http://host.docker.internal:8000` (verified 2026-09-25). The only public entry point is the Cloudflare quick tunnel, and every `/v1` route requires an API key.

## D11. One `jobs` table for sync and async extraction (P2)
`/v1/extract/sync` writes a `jobs` row (`mode=sync`) for every document that gets as far as a result. P4's `/v1/jobs` reuses the same table and pipeline (`services/extract.py`), so the two paths can't drift apart.

Job ids are `job_` + a ULID: sortable, no dependency, and they match the contract's `job_01J...`. JSON columns are `jsonb` because they're queried. Responses are always rebuilt through the Pydantic contract models, so field order never depends on storage (compare D6).

## D12. Confidence = model self-report + deterministic grounding
The model's self-reported confidence alone doesn't mean much, so every extracted value is also checked against the PDF text. The check tries formatting variants:
- amounts: `1,296.00`, `1296.00` and `1.296,00`, matched on number boundaries so `96.00` doesn't match inside `1,296.00`;
- about a dozen date formats;
- invoice numbers and descriptions compared with only letters and digits kept;
- currency codes and symbols.

| Score | Rule |
|---|---|
| Field | `0.5 × self-report + 0.5 × grounded`, capped at 0.5 if a validation error names the field |
| Overall | `0.5 × mean(fields) + 0.5 × min(vendor, invoice_no, invoice_date, total)`, so one ungrounded critical field is enough to send the invoice to review |

Rounding is half-up via Decimal; plain `round()` turns 0.975 into 0.97. The review threshold is 0.85 (brief).

## D13. The repair pass must not "fix" the invoice
When validation fails, there is exactly one re-prompt, and it lists the errors. The repair prompt tells the model to correct *misreadings* but never to change printed values just to make the arithmetic pass.

A vendor invoice that genuinely doesn't add up has to reach a human (`needs_review`, with the printed values and the error kept). It must not be silently "corrected" into a number nobody billed. The synthetic set includes deliberate `bad_totals` invoices to test exactly this.

## D14. Duplicates are flagged, not rejected
`dedupe_hash = sha256(normalized vendor | normalized invoice_no | total)`. Normalizing strips legal suffixes like Ltd, Limited and GmbH, uppercases the invoice number and keeps only letters and digits. `duplicate_of` points to the earliest earlier job with data. The status is still computed normally.

The routing decision ("duplicate → log and stop") belongs to the workflow (n8n), in line with the brief's rule that no-code flows decide what happens. A re-sent copy in a different layout still matches, because the hash uses the extracted fields, not the file bytes.

## D15. Extraction failures map to distinct HTTP answers
| Situation | Response |
|---|---|
| LLM unavailable (timeout, 5xx, provider disabled) | **503** with `Retry-After`; no job is stored and the idempotency key is released |
| Not a PDF | 415 (images mention that OCR isn't available) |
| Over 5 pages | 413 (use `/v1/jobs`, P4) |
| Unknown schema or unreadable PDF | 422 |
| Blank or scanned PDF | 200 with `status: failed` and a `no_text_layer` error |

A blank or scanned PDF is a valid request whose document simply has no usable data, so it gets a stored result.

## D16. Synthetic invoices are deterministic and reuse the same prefix
`evals/generate_invoices.py` builds invoice *i* from its own seed, rotating through 6 fictional vendors (GBP/USD/EUR/PKR/CAD, US and EU number formats, 6 date formats) and 3 layouts. Any set of N is the first N of a larger set, so the P2 samples stay part of the P6 eval set.

Labels store the values *as printed*. `bad_totals` and `duplicate` cases sit at fixed indices, with their expected status and expected `duplicate_of`.

## D17. Local LLM: `qwen3:4b-instruct-2507` on Ollama (2026-10-02)
OpsCore runs its LLM locally: Ollama in the compose stack, on a GTX 1660 SUPER with 6 GB of VRAM. Ollama reports about 5 GB available. Only one model fits at a time, so a single model handles both enrichment and extraction. The settings are `LLM_PROVIDER=openai_compat`, `LLM_JSON_MODE=structured`, `LLM_REASONING_EFFORT=none` and temperature 0.

**Why this model.** Measured with `evals/bench_llm.py`, using the same 10 homepages (2,000 characters each) and the same 5 invoices for every model:

| Model (Q4) | Invoices exact | Status as expected | Extract p50 | Enrich LLM p50 / max | First call incl. load |
|---|---|---|---|---|---|
| **qwen3:4b-instruct-2507** | **5/5** | 4/5 | **6.7 s** | 3.2 s / 3.8 s | 35.0 s |
| granite4.2:3b | 1/5 | 4/5 | 9.8 s | 2.8 s / 3.4 s | 9.5 s |
| qwen3.5:4b | 0/5 | 5/5 | 9.3 s | 3.9 s / 4.1 s | 41.9 s |
| qwen2.5:3b | 0/5 | 3/5 | 7.8 s | 2.1 s / 2.6 s | 5.5 s |

Sources: `evals/results/bench_llm_20261002T123539Z.json`; qwen2.5 comes from `bench_llm_20260925T163302Z.json`.
- **qwen2.5 and qwen3.5** left every due date empty.
- **qwen2.5** also misread European decimals, for example 30,29 as 3029.
- **granite**'s amounts were right, but it added "INVOICE" to vendor names and copied whole lines into descriptions.

The shortlist came from a deep-research pass (`reports/Open models for 6GB VRAM.md`). Its quality scores are vendor-reported, so the choice rests on these local runs, not on the leaderboards.

**What to watch:**
- **Thinking models need `reasoning_effort: "none"`.** With thinking on, granite4.2:3b spent 64 tokens on a trivial JSON call. With it off, the same call took 10 tokens and 161 ms. `think: false` was ignored on Ollama's OpenAI-compatible endpoint.
- **Cold start.** The first call after a restart pays the model-load time from the table. `OLLAMA_KEEP_ALIVE=-1` keeps the model in VRAM afterwards: 3.2 GB, 100% GPU, 4,096-token context. Warm it up before a demo.
- **Page text.** 2,000 characters instead of 6,000 cut the enrichment LLM's p50 from about 6.1 s to 2.8 s on granite. Benchmarked prompts were about 1,500 tokens at 6,000 characters.
- **No price.** `cost_usd` stays null for the local model; we don't invent a price.

## D19. Confidence weights grounding 0.75, self-report 0.25 (2026-10-02)
D12 changes from a 50/50 blend to `field = 0.25 × self-report + 0.75 × grounded`. The 0.5 cap when a validation error names the field stays, and so does the overall formula.

**Diagnosis (inv_003, qwen3 4B):**
- Every value was correct and was found in the PDF, and validation passed.
- The model reported `invoice_no` confidence **0.0** anyway. The letter layout labels it "Invoice ref:".
- With 50/50 weighting that one self-report pulled the overall score to 0.72, and a correct invoice went to `needs_review`.
- Under 25/75 the field scores 0.75 and the overall 0.86, so the invoice is `done`. The 20-invoice run confirms it: `bench_llm_20261002T191514Z.json` shows inv_003 `done` at 0.86.

**Boundaries, pinned in `tests/test_validate.py`:**

| Case | Overall | Outcome |
|---|---|---|
| Ungrounded value, even with self-report 1.0 | field ≤ 0.25 | Below the threshold → `needs_review` |
| Two doubted but grounded critical fields | exactly 0.85 | `done` |
| Three doubted fields | 0.83 | `needs_review` |

Status is decided on the same rounded number the API returns.

## D20. Duplicate detection is scoped per API key (2026-10-02)
`find_duplicate` only matches earlier jobs from the **same** API key. Before this change, one client's invoice could be flagged as a duplicate of another client's. That would tell the second client that someone else holds the same invoice: a cross-tenant leak. Tested in `test_duplicates_are_not_matched_across_clients`.

## D21. Invoice numbers must match a whole token (2026-10-02)
Grounding for `invoice_no` now uses `identifier_in_text`, which compares exact tokens and adjacent token pairs, with letters and digits only. It replaced substring matching.

**The bug:** on held-out inv_015 the model returned `RE-26-843` for `RE-26-8437`, dropping a digit. Substring matching found "RE26843" inside "RE268437", so the wrong number passed as `done` at 0.86 (`bench_llm_20261002T191514Z.json`).

**After the fix:** the model dropped a trailing digit three more times on the fresh invoices 21–40: inv_030 and inv_031 under prompt v1, inv_036 under v2. All three ended in `needs_review`, at confidence 0.44–0.58.

**Deliberately strict:**
- No suffix or prefix rule: such a rule would also accept a value missing its *leading* characters.
- So a label glued to the value ("No:INV-2041") counts as not found. That gives a false review, never a false `done`.
- `test_pdf_text` shows the strict match still finds the real number on all 20 generated invoices, across all 3 layouts.

## D22. Extraction prompt v2, chosen on unseen invoices (2026-10-02)
`PROMPT_VERSION = "invoice_extract_v2"`. Its rules target the failure classes seen on invoices 6–20:
- descriptions carry only the item name, with no "N x" prefix and no price;
- numbers inside a name are not the quantity;
- every character of the invoice number;
- the common due-date labels;
- no document title in the vendor name;
- European number formats.

**Avoiding overfitting.** Invoices 1–20 had been inspected, so v1 and v2 were compared on **invoices 21–40**, generated only for this test. The generator is prefix-stable, so these documents were never looked at while writing either prompt. Same model and settings for both runs:

| | v1 | v2 |
|---|---|---|
| Exact match | 9/20 | **15/20** |
| Status as expected | 17/20 | **19/20** |
| Wrong data that still ended `done` | 8 | **4** |
| Repair passes | 3 | 1 |
| Extract p50 | 5.96 s | 6.06 s |
| Field errors | descriptions 14, invoice no. 2, qty 1 | due date 3, descriptions 2, invoice no. 1 |

Sources: `bench_llm_20261002T191955Z.json` (v1) and `bench_llm_20261002T192208Z.json` (v2).
- In neither run did a wrong amount, quantity or invoice number reach `done`. Validation and D21 caught all of them.
- **Known regression:** v2 missed 3 due dates that v1 found, on inv_022, inv_025 and inv_031, all on the classic layout. It stays open for P6 and gets checked on a further unseen set (41+), never on 21–40 again.

## D18. Enrichment budget is 9 s on the local-GPU setup (2026-10-02)
`ENRICH_BUDGET_S=9`, `FETCH_TIMEOUT_S=4` and `LLM_TIMEOUT_S=5`. This deliberately departs from the brief's "under 5 s". The brief assumed a hosted model; here the homepage fetch from inside Docker took about 3 s at the median, with a long tail up to 17.7 s on one site (2026-09-25 run), and the local LLM step takes about 3 s. A 4.8 s budget left most leads without an industry.

End-to-end `/v1/leads/enrich` on the 10 test-lead domains, measured with `evals/bench_enrich_e2e.py` and an empty cache:

| | Before: 4.8 s budget, granite4.2:3b, site_enrich_v1 | After: 9 s budget, qwen3 4B, site_enrich_v3 |
|---|---|---|
| Industry filled | 3/10 | **10/10** |
| p50 / max | 4.7 s / 5.1 s | 2.5 s / 8.3 s |
| Answered under 5 s | 9/10 | 9/10 |

**Caveats:**
- **Confounded comparison.** The model, the prompt and the budget all changed between the two columns, so this is the combined effect, not the budget's alone.
- **Unexplained speed.** The after-run's p50 (2.5 s) is lower than the LLM-only p50 measured minutes earlier (3.0 s). It is re-measured during the LeadRouter test run before any README or resume quotes a figure.
- **Zapier gate.** The Webhooks step's timeout is checked on Zapier trial day 1. If it's below about 10 s, this budget goes back down.

## D23. The model reports a stated headcount; code assigns the size band (2026-10-02)
`site_enrich_v3` asks for `employee_count_stated` (an integer, or null), and `scoring.size_band_for` maps it to the band. The public `size_band_guess` field is unchanged. History:
- **v1** answered "1-10" for 8 of 10 real homepages (`bench_llm_20261002T192357Z.json`). None of those pages states a headcount: a regex check of the first 2,000 characters found none. Its own rules had also wrongly listed customer counts as evidence.
- **v2** returned "unknown" for all 10, but on a synthetic page saying "more than 350 employees" it chose `51-200`.
- **v3** passed all three synthetic checks:
  - 40 people → `11-50`;
  - 350 employees → `201-1000`;
  - "2,000 dispatchers" with no headcount → `unknown`.

  It also gave unknown on all 10 real sites (`bench_llm_20261002T192743Z.json`). The band boundaries are tested in `test_size_band_for_stated_headcount`.

## D24. Async jobs: PDF in Postgres, a sync worker around the shared pipeline, reviews kept separate (2026-10-02)
- **The uploaded PDF goes into `job_files`** (bytea, ≤10 MB), committed in the same transaction as the `jobs` row. Only then is the Celery task queued, so the worker always finds both, and there is no shared volume to clean up or keep consistent. The trade-off is that large or high-volume files would belong in object storage; that's out of scope here.
- **The worker is synchronous Celery code** that calls the existing async `extract_invoice` through `asyncio.run`. Both endpoints write and render jobs through the same helpers (`apply_outcome`, `job_to_response`), so the sync and async paths can't drift apart.
- **`POST /v1/jobs` is idempotent** on the `Idempotency-Key` header, or, if none is sent, on `sha256:<file hash>`. Re-sending the same PDF returns the same `job_id` with `Idempotent-Replay: true`. Evidence: `docs/evidence/p4_idempotent_replay.txt`.
- **`POST /v1/jobs/{id}/review` writes to `job_reviews`.** It never overwrites `jobs.data`, so model output and human truth stay side by side for P6 evals. Status becomes `reviewed`.
- **`/metrics` is not built.** It's on the brief's cut list ("use logged latency instead"); latency, attempts and tokens are in the JSON logs.

## D25. Job retries: exponential backoff with equal jitter, at most 3 attempts (2026-10-02)
Retryable LLM or transport errors (timeout, connection, 429, 5xx) re-run the job through `self.retry`. The delay is `base × 2^(n-1)`, half fixed and half random. With `JOB_RETRY_BACKOFF_S=10` that means 5–10 s, then 10–20 s.

Celery's `autoretry_for` + `retry_jitter` uses *full* jitter (anywhere from 0 to the delay). That can retry almost instantly while the dependency is still restarting, which is exactly when retries matter. So the brief's `autoretry_for` is replaced by an explicit retry with a floor.

After the third failed attempt, `on_failure` marks the job `failed` (`llm_unavailable`), and the callback still goes out, so the caller is never left waiting.

**Evidence** (`docs/evidence/p4_retry_killed_llm.log`): Ollama was stopped before the job was submitted.

| Time | Event |
|---|---|
| 20:14:07 | Attempt 1 fails with `connection error`; retry scheduled |
| 20:14:15 | Attempt 2 starts, 7.7 s later |
| 20:14:37 | Attempt 2 finishes `done` |

## D26. Callbacks: HMAC-signed, SSRF-checked, TLS pinned, never `verify=False` (2026-10-02)
**Signing.** `X-OpsCore-Signature: sha256=HMAC_SHA256(secret, f"{timestamp}." + raw_body)` plus `X-OpsCore-Timestamp`. The timestamp is inside the signed message, so it can't be swapped, and receivers reject anything older than 5 minutes. `app/core/signing.py` includes the reference verifier.

**Where callbacks may go.** Callback URLs come from authenticated clients but still make our server connect somewhere:
- **Public hosts:** every resolved address must be public, as with the homepage fetch (D7).
- **Non-public hosts:** allowed only through `CALLBACK_HOST_MAP`. That covers n8n, whose resume URLs say `https://localhost:5678/...` because no `WEBHOOK_URL` is set.

**How it connects to n8n.** OpsCore connects to the mapped target (`host.docker.internal`) and keeps `localhost` as the Host header and TLS SNI. It verifies the certificate against a **pinned** copy of n8n's self-signed certificate (`CALLBACK_CA_FILE`; CN/SAN `localhost`, `127.0.0.1`). Checked live: the handshake succeeds with the pinned certificate and is **rejected** with the system certificates.

**Retries and logging.** Every attempt is logged to `webhook_deliveries`. Non-2xx responses and network errors retry with backoff, up to 6 attempts.

**The n8n side.** n8n's Crypto v2 node reads the HMAC secret from a **Crypto credential**, so the secret never appears in exported workflow JSON.

## D27. Live end-to-end run of all 40 invoices through the API (2026-10-02)
`scripts/extract_samples.ps1` ran against the running API with `qwen3:4b-instruct-2507`, `invoice_extract_v2`, `site_enrich_v3` and every fix through D23:

| Result | Count |
|---|---|
| HTTP 200 | **40/40** |
| Ended in the expected status | **36/40** |
| Matched the label exactly | **31/40** |

- **The 4 status misses** (inv_004, 010, 016, 028) are all the same vendor line, "Object storage 1 TB", whose quantity was misread. Validation flagged every one (`line_amount_mismatch`), so they went to `needs_review`, not through.
- **All 3 bad-totals invoices** were correctly sent to `needs_review`.
- **5 wrong invoices still ended `done`.** Their errors were 4 missing due dates (inv_007, 009, 022, 031) and 2 descriptions that dropped "1 TB" (inv_022, 034). **No wrong amount, quantity or invoice number reached `done`.** Due-date recall is the main open extraction issue for P6.
- **Caveat:** invoices 1–40 include the sets inspected while writing prompts v1/v2 (1–20) and the v1-vs-v2 comparison set (21–40). This is a pipeline check, not a fresh held-out score.

## D28. Permanent 4xx callback responses are not retried

**Context.** In the P4 n8n test (`docs/evidence/p4_n8n_signed_callback.txt`), a callback that reached an n8n Wait execution after it had already finished got `409 "The execution has finished already"`. OpsCore kept retrying it until it hit `CALLBACK_MAX_ATTEMPTS` (6), even though no retry could ever succeed.

**Decision.** A 4xx response means the receiver understood the request and refused it, so the delivery is logged once and then stops (`send_callback` returns `"refused"`). Three 4xx codes do mean "try again later": 408 Request Timeout, 425 Too Early and 429 Too Many Requests. Those, plus 5xx responses and transport errors, keep the existing backoff and attempt limit (D25 and D26).

**Evidence.** `tests/test_jobs.py::test_permanent_4xx_callbacks_are_not_retried`: 409 and 404 produce 1 logged attempt; 429 and 408 produce 6. Full suite: 146 tests pass.

## D29. Eval method, slices and the CI gate, fixed before the P6 runs (2026-10-19)
**Why it is written down first:** the gate thresholds and the meaning of each slice are decided before any P6 number exists, so they can't be bent to fit the results.

**Invoice slices (never blended into one number):**
- `dev`: invoices 1–20, inspected while writing prompts v1/v2 and the confidence fix.
- `val`: invoices 21–40, used to choose v2 over v1 (D22).
- `test_same_template`: invoices 41–60, generated for P6 from the same generator. These are **new instances of the same 3 templates**, so this slice says how the pipeline does on new invoices of known layouts, not on new layouts. 1 duplicate (52 re-sends 44) and 2 bad-totals (41, 53).
- `test_new_layout`: 8 invoices from `evals/generate_invoices_alt.py`, a separately written template with different vendors, currencies (AUD, USD, CHF, NOK), labels, date formats and number styles, and no ruled table. 1 has a bad total. It is the fairest generalisation check.
- Neither test slice was opened, printed or run before the final P6 runs. Both generators suppress printing test invoices.

**Lead slices:**
- `leads_dev`: the 14 tier-labelled LeadRouter test leads, which were used while building LeadRouter.
- `leads_test`: 16 new synthetic leads, labelled blind by the owner in `evals/data/leads_to_label.csv` before any model run on them.
- Both use fixed enrichment blocks, so they don't depend on live websites: a frozen copy of OpsCore's `domain_cache` for the real dev domains, and written blocks for the fictional test companies.
- The chain is LeadRouter's `prepare_lead.py`, then `lead_icp_v1` through OpsCore's LLM client, then `score_lead.py`. Zapier's own AI step uses Zapier's model, so this scores the prompt and the scoring code, not Zapier's model.

**Sampling and repeats:**
- temperature 0 (already the OpenAI-compatible default) and seed 42 (new optional `LLM_SEED`, sent only when set);
- `LLM_TEMPERATURE` overrides the Anthropic default of 1.0, for a hosted-model comparison (not run: owner's choice);
- test slices run 3 times, and the report shows the median and the min–max range;
- every metric carries its `n`.

**Metrics:**
- field accuracy over 8 header fields;
- documents fully exact;
- status as expected;
- line-item precision, recall and F1 (lines match on normalised description, qty, and unit price/amount within half a cent);
- totals reconcile (on invoices whose printed totals add up);
- first-call invalid JSON/schema;
- repair passes;
- wrong data that still ended `done`, split into money/number/invoice-number fields (`invoice_no`, `currency`, `subtotal`, `tax`, `total`, line qty/unit price/amount or line count) and other fields (vendor, dates, descriptions);
- model time per document (p50/p95) and tokens.

Cost is $0 for the local model. A hosted-API cost would be a list-price estimate from measured tokens, but no hosted run was made (owner's choice), so every reported run is local.

**Gate** (`python -m evals.run_evals gate` / `ci`):
- **Replay (CI):** with recorded answers, every gated metric must equal the baseline exactly.
- **Re-record (live):** per slice, the median field accuracy (invoices) or final tier accuracy (leads) may not drop by more than **5 points**. Invalid JSON may not rise above the baseline. Valid lead answers may not fall below it.
- **Wrong money/number/invoice-number values reaching `done`:** "no new cases beyond the baseline list". Each known case is stored as (slice, document, field). Any case found in the P6 runs is reported as an open defect, in the report and in D30. Fixing it (for example, a stricter confidence rule for money fields) is a separate decision: it is measured on dev/val only, and then a new baseline is recorded. The gate is not loosened to make a run pass.

**Cassettes:**
- Live runs save every raw model answer to `evals/cassettes/`.
- The key includes provider, model, model digest, temperature, seed, JSON mode, reasoning setting, max_tokens, prompt, input and schema.
- A replay miss fails CI, which forces a re-record after any prompt or model change.

**Amendment (2026-10-19, before any lead model run).** The owner's first two attempts at blind labelling of `leads_test` in the chat tool followed button order rather than the leads (for example, the whole first batch was the first option), so those answers were not used. The owner then delegated the labels. Claude labelled the 16 leads from the written ideal-client rubric in `prompts/lead_icp_v1.md` (size 11–200, an offered service, budget $2k+, start within about 3 months, company email, a concrete problem), and recorded the reason for each label in `evals/data/leads_test_label_notes.md`. Because the labeller also wrote the prompt, `leads_test` is **not an independent test**. It is reported separately from `leads_dev`, and every lead number is read with that caveat.

## D30. What the P6 eval runs found (2026-10-19)
**Source:** `evals/report.md`, generated from `evals/results/run_20261019T161500Z_invoices_v2.json`, `run_20261019T194222Z_invoices_v1.json` and `run_20261019T195922Z_leads_leads.json`.
- **Setup:** qwen3 4B Q4_K_M on a GTX 1660 SUPER, temperature 0, seed 42. Test slices ran 3 times.
- **Replay:** CI replays all three runs exactly (`docs/evidence/p6_ci_local.txt`).

**Invoices, production prompt v2:**
- **Wrong amounts never got through.** No wrong amount, quantity or invoice number reached `done` in any slice (dev 20, val 20, test_same_template 20 × 3 runs, test_new_layout 8 × 3 runs).
- **Same-template test (n=20):** 93.1% field accuracy, 15/20 documents fully exact, 17/20 status as expected, line-item F1 0.945. All 3 runs were identical.
  - One document, inv_057, produced schema-invalid output on the first call and again after repair, so it ended `failed`. That one document takes all 8 of its fields to zero.
  - The two harmless misses that still reached `done` were a missing due date and a description that dropped "1 TB".
- **New layout (n=8):** 98.4% field accuracy, but only 5/8 fully exact and 4/8 status as expected.
  - On the Norwegian invoices the model misread amounts written with a space as the thousands separator (`1 754,49` became `754.49`).
  - It also garbled one Swiss invoice number.
  - Validation caught every one, so they went to `needs_review`. One correct invoice (alt_007) was flagged anyway, a cautious false alarm.
- **Due-date recall** is still the main gap on the known templates: 17/20 on val and on test_same_template.

**v1 against v2 on unseen data** (confirms D22):
- On the same-template test, v1 is slightly *higher* on header fields: 99.4% vs 93.1%. The gap is v2's single hard failure, inv_057.
- v1 is far weaker on line items (F1 0.543 vs 0.945) and on fully exact documents (10/20 vs 15/20).
- **v1 let a wrong quantity and unit price reach `done` on the new layout** (alt_001), and v2 did not. v2 stays.

**Leads** (`lead_icp_v1` + LeadRouter scoring; both slices labelled by Claude from the rubric, so not independent):
- Final tier correct: 11/14 on `leads_dev` and 10/16 on `leads_test` (all 3 runs identical).
- The AI tier alone: 9/14 and 10/16.
- Spam recall 2/2 and 3/3. Valid JSON 30/30.
- **Main weakness: over-scoring.** The model gives fit scores of 85–95 to leads the rubric calls warm, so hot precision is only 5/8 and 4/8.
- One cold lead (N10, an app built from scratch) was scored 0 and marked spam.
- Blending with the rules score helped on dev (+2) but not on test.

**Open items, not fixed in P6** (each needs its own dev/val-only change and then a new baseline, per D29):
- a hard-failure fallback for inv_057-type schema errors;
- number-format normalisation for space-grouped amounts;
- due-date recall;
- lead score calibration, for example a rubric-based cap when budget or timeline is outside the ideal range.
