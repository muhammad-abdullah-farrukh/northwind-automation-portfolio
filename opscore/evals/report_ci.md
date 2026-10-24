# OpsCore eval report

Generated 2026-10-19 20:06 UTC by `python -m evals.run_evals report` from the run files listed per section.
Every number below comes from those runs; nothing is typed in by hand. Method, splits and gate: DECISIONS D29.

**How to read this**
- Hardware: NVIDIA GeForce GTX 1660 SUPER, 6 GB VRAM (driver 610.88); Ollama ?; local model digest `0edcdef34593`. Latencies are model time on that machine. Local runs cost $0; hosted-API costs are list-price estimates from measured tokens.
- Sampling: temperature 0 and a fixed seed. Test slices run several times; ranges show run-to-run spread.
- Slices are never blended. `dev` (1-20) and `val` (21-40) were seen while writing prompts and choosing v2, so they are not unbiased. `test_same_template` (41-60) is new instances of the same 3 templates; `test_new_layout` (8) is a separately written template, the fairest generalisation check.
- Small samples: one invoice is 5 points on n=20, 12.5 on n=8; one lead is about 7 points on n=14 or 6 on n=16.
- Leads: Zapier's AI step uses Zapier's own model; these runs score the same prompt and LeadRouter's scoring code on the local model. `leads_dev` (14) was used while building LeadRouter. `leads_test` (16) was labelled by Claude from the written ideal-client rubric, at the owner's request, before any model run on it; the labeller also wrote the prompt, so neither lead slice is independent.

### Invoices: `invoice_extract_v2` on `qwen3:4b-instruct-2507-q4_K_M` (openai_compat)

Run `20261019T200644Z_invoices_ci_v2` (replay); source: `evals/results/ci_20261019T161500Z_invoices_v2.json`.

| Metric | dev (n=20) | val (n=20) | test_same_template (n=20) | test_new_layout (n=8) |
|---|---|---|---|---|
| Field accuracy (8 header fields) | 99.4% | 98.1% | 93.1% (identical in 3 runs) | 98.4% (identical in 3 runs) |
| Documents fully exact | 16/20 (80%) | 15/20 (75%) | 15/20 (75%) (identical in 3 runs) | 5/8 (62%) (identical in 3 runs) |
| Status as expected | 17/20 (85%) | 19/20 (95%) | 17/20 (85%) (identical in 3 runs) | 4/8 (50%) (identical in 3 runs) |
| Line items F1 | 0.933 | 0.923 | 0.945 (identical in 3 runs) | 0.842 (identical in 3 runs) |
| Totals reconcile | 18/18 (100%) | 19/19 (100%) | 17/18 (94%) (identical in 3 runs) | 5/7 (71%) (identical in 3 runs) |
| First-call invalid JSON/schema | 0/20 (0%) | 0/20 (0%) | 1/20 (5%) (identical in 3 runs) | 0/8 (0%) (identical in 3 runs) |
| Repair passes | 7/20 (35%) | 2/20 (10%) | 4/20 (20%) (identical in 3 runs) | 7/8 (88%) (identical in 3 runs) |
| Wrong data still `done` | 1/20 (5%) | 4/20 (20%) | 2/20 (10%) (identical in 3 runs) | 0/8 (0%) (identical in 3 runs) |
| …of which money/number/invoice no. fields | 0 | 0 | 0 (identical in 3 runs) | 0 (identical in 3 runs) |
| LLM time per doc, p50 | 6.2 s | 6.0 s | 6.6 s (range 6.5 s to 6.7 s, 3 runs) | 13.9 s (range 13.7 s to 14.6 s, 3 runs) |
| LLM time per doc, p95 | 16.4 s | 16.3 s | 13.7 s (range 13.3 s to 14.1 s, 3 runs) | 14.4 s (range 14.3 s to 16.8 s, 3 runs) |
| Tokens per doc (mean) | 1636 | 1240 | 1377 (identical in 3 runs) | 2522 (identical in 3 runs) |
| Cost | $0 (local model) | $0 (local model) | $0 (local model) (identical in 3 runs) | $0 (local model) (identical in 3 runs) |

Per-field accuracy (first run of each slice):

| Field | dev | val | test_same_template | test_new_layout |
|---|---|---|---|---|
| vendor | 20/20 (100%) | 20/20 (100%) | 19/20 (95%) | 8/8 (100%) |
| invoice_no | 20/20 (100%) | 20/20 (100%) | 18/20 (90%) | 7/8 (88%) |
| invoice_date | 20/20 (100%) | 20/20 (100%) | 19/20 (95%) | 8/8 (100%) |
| due_date | 19/20 (95%) | 17/20 (85%) | 17/20 (85%) | 8/8 (100%) |
| currency | 20/20 (100%) | 20/20 (100%) | 19/20 (95%) | 8/8 (100%) |
| subtotal | 20/20 (100%) | 20/20 (100%) | 19/20 (95%) | 8/8 (100%) |
| tax | 20/20 (100%) | 20/20 (100%) | 19/20 (95%) | 8/8 (100%) |
| total | 20/20 (100%) | 20/20 (100%) | 19/20 (95%) | 8/8 (100%) |

Wrong money/number/invoice-number values that reached `done`: **none**.

### Invoices: `invoice_extract_v1` on `qwen3:4b-instruct-2507-q4_K_M` (openai_compat)

Run `20261019T200647Z_invoices_ci_v1` (replay); source: `evals/results/ci_20261019T194222Z_invoices_v1.json`.

| Metric | dev (n=20) | val (n=20) | test_same_template (n=20) | test_new_layout (n=8) |
|---|---|---|---|---|
| Field accuracy (8 header fields) | 100.0% | 98.8% | 99.4% (identical in 3 runs) | 100.0% (range 98.4% to 100.0%, 3 runs) |
| Documents fully exact | 12/20 (60%) | 9/20 (45%) | 10/20 (50%) (identical in 3 runs) | 4/8 (50%) (range 3/8 (38%) to 4/8 (50%), 3 runs) |
| Status as expected | 18/20 (90%) | 17/20 (85%) | 18/20 (90%) (identical in 3 runs) | 3/8 (38%) (range 2/8 (25%) to 3/8 (38%), 3 runs) |
| Line items F1 | 0.689 | 0.641 | 0.543 (identical in 3 runs) | 0.700 (range 0.650 to 0.700, 3 runs) |
| Totals reconcile | 18/18 (100%) | 19/19 (100%) | 18/18 (100%) (identical in 3 runs) | 5/7 (71%) (range 4/7 (57%) to 5/7 (71%), 3 runs) |
| First-call invalid JSON/schema | 0/20 (0%) | 1/20 (5%) | 0/20 (0%) (range 0/20 (0%) to 1/20 (5%), 3 runs) | 0/8 (0%) (identical in 3 runs) |
| Repair passes | 4/20 (20%) | 3/20 (15%) | 3/20 (15%) (range 3/20 (15%) to 4/20 (20%), 3 runs) | 5/8 (62%) (identical in 3 runs) |
| Wrong data still `done` | 6/20 (30%) | 8/20 (40%) | 8/20 (40%) (identical in 3 runs) | 1/8 (12%) (identical in 3 runs) |
| …of which money/number/invoice no. fields | 0 | 0 | 0 (identical in 3 runs) | 2 (identical in 3 runs) |
| LLM time per doc, p50 | 6.3 s | 6.1 s | 6.1 s (range 6.1 s to 6.7 s, 3 runs) | 11.6 s (range 11.0 s to 14.2 s, 3 runs) |
| LLM time per doc, p95 | 14.8 s | 15.8 s | 11.4 s (range 11.2 s to 15.8 s, 3 runs) | 16.1 s (range 16.0 s to 21.0 s, 3 runs) |
| Tokens per doc (mean) | 1115 | 1042 | 1046 (range 1046 to 1112, 3 runs) | 1762 (range 1762 to 1769, 3 runs) |
| Cost | $0 (local model) | $0 (local model) | $0 (local model) (identical in 3 runs) | $0 (local model) (identical in 3 runs) |

Per-field accuracy (first run of each slice):

| Field | dev | val | test_same_template | test_new_layout |
|---|---|---|---|---|
| vendor | 20/20 (100%) | 20/20 (100%) | 20/20 (100%) | 8/8 (100%) |
| invoice_no | 20/20 (100%) | 18/20 (90%) | 19/20 (95%) | 8/8 (100%) |
| invoice_date | 20/20 (100%) | 20/20 (100%) | 20/20 (100%) | 8/8 (100%) |
| due_date | 20/20 (100%) | 20/20 (100%) | 20/20 (100%) | 8/8 (100%) |
| currency | 20/20 (100%) | 20/20 (100%) | 20/20 (100%) | 8/8 (100%) |
| subtotal | 20/20 (100%) | 20/20 (100%) | 20/20 (100%) | 7/8 (88%) |
| tax | 20/20 (100%) | 20/20 (100%) | 20/20 (100%) | 8/8 (100%) |
| total | 20/20 (100%) | 20/20 (100%) | 20/20 (100%) | 8/8 (100%) |

Wrong money/number/invoice-number values that reached `done`: test_new_layout:alt_001.pdf:line_items.qty, test_new_layout:alt_001.pdf:line_items.unit_price

### Leads: `lead_icp_v1` on `qwen3:4b-instruct-2507-q4_K_M` + LeadRouter scoring code

Run `20261019T200650Z_leads_ci_leads` (replay); source: `evals/results/ci_20261019T195922Z_leads_leads.json`.

| Metric | leads_dev (n=14) | leads_test (n=16) |
|---|---|---|
| Final tier correct (0.6 × AI + 0.4 × rules) | 11/14 (79%) | 10/16 (62%) (identical in 3 runs) |
| AI tier alone correct | 9/14 (64%) | 10/16 (62%) (identical in 3 runs) |
| Spam precision | 2/2 (100%) | 3/4 (75%) (identical in 3 runs) |
| Spam recall | 2/2 (100%) | 3/3 (100%) (identical in 3 runs) |
| Hot precision | 5/8 (62%) | 4/8 (50%) (identical in 3 runs) |
| Valid JSON answers | 14/14 (100%) | 16/16 (100%) (identical in 3 runs) |
| LLM time per lead, p50 | 3.1 s | 3.2 s (range 3.2 s to 3.3 s, 3 runs) |
| LLM time per lead, p95 | 3.4 s | 3.6 s (range 3.6 s to 3.9 s, 3 runs) |

Confusion, final tier, leads_dev (rows = label, columns = predicted; first run):

| label \ predicted | hot | warm | cold | spam |
|---|---|---|---|---|
| hot | 5 | 0 | 0 | 0 |
| warm | 3 | 1 | 0 | 0 |
| cold | 0 | 0 | 3 | 0 |
| spam | 0 | 0 | 0 | 2 |

Confusion, final tier, leads_test (rows = label, columns = predicted; first run):

| label \ predicted | hot | warm | cold | spam |
|---|---|---|---|---|
| hot | 4 | 0 | 0 | 0 |
| warm | 4 | 1 | 0 | 0 |
| cold | 0 | 1 | 2 | 1 |
| spam | 0 | 0 | 0 | 3 |

