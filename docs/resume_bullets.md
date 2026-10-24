# Resume and Fiverr bullets (measured numbers only)

Every number comes from a recorded run. The sources are listed under each bullet, and the brief's rule applies: no invented metrics. Re-check the numbers against the source files after any re-run.

## Automation Engineer, Northwind Digital portfolio (Python · FastAPI · n8n · Zapier · local LLM)

- **Built OpsCore**, a FastAPI + Celery service that extracts and validates supplier invoices with a local 4B model (qwen3 on a 6 GB GTX 1660 SUPER, $0 per document). Accuracy on 20 unseen invoices:
  - 93.1% header-field accuracy;
  - 0.945 line-item F1;
  - **no wrong amount, quantity or invoice number auto-approved** in any test run.

  *Sources: `opscore/evals/report.md`, `run_20261019T161500Z_invoices_v2.json`.*

- **Designed the validation-first pipeline.** It has deterministic checks (line maths, totals, invoice-number grounding), one repair pass and a confidence threshold. On a layout the prompt was never tuned on (n=8), it caught every misread amount (for example `1 754,49` read as `754.49`) and sent it to human review instead of the ledger.

  *Source: report, `test_new_layout`.*

- **Built an eval harness and a CI gate.**
  - Slices are kept separate (dev / val / same-template test / new-layout test), and runs are repeated 3 times with a fixed seed.
  - CI replays the recorded model answers, so it needs no GPU or API key, and fails on any score change.
  - It caught that the older prompt let a wrong quantity through on unseen data; the production prompt did not.

  *Sources: DECISIONS D29/D30, `docs/evidence/p6_ci_local.txt`.*

- **Automated accounts payable in n8n (InvoiceIQ).** Email or form intake runs one execution per PDF and verifies the HMAC-signed callback (with a 5-minute freshness check). Uncertain invoices get a Slack approval form, then go to the Postgres + Google Sheets ledger, with an error workflow for failures. In the acceptance run of 10 emailed invoices:
  - 8 filed, 2 of them after Slack review (one with a corrected total);
  - 1 duplicate skipped;
  - 1 unreadable scan alerted.

  *Source: `invoiceiq/README.md`, acceptance run.*

- **Built a finance Q&A agent** on a local LLM. LLM-written SQL runs as a read-only Postgres role behind a query guard, alongside pgvector search and a review-queue tool. It answered 5 of 5 test questions correctly, citing invoice numbers, after one prompt fix (4 of 5 before).

  *Source: `invoiceiq/README.md`.*

- **Found and fixed a lost-update race in the live run.** n8n's Google Sheets node computes the row number itself, so 6 near-simultaneous appends left only 2 rows. Switching to Google's own `INSERT_ROWS` append was proven with 8 parallel writes, 8 of 8 kept.

  *Source: `invoiceiq/README.md`, "Sheet append race".*

- **Built a Zapier lead router (LeadRouter).** A Python Code step validates the lead, OpsCore enriches it, an AI fit score is blended with a rules score (0.6 / 0.4), and Paths route it to Zoho CRM, Slack, Gmail drafts or Sheets. Measured on 14 + 16 labelled leads with the same prompt on the local model:
  - final tier correct 11/14 and 10/16;
  - spam recall 5/5.

  On Zapier itself, all 15 synthetic leads ended on their expected path (14/14 tiers correct; the invalid email was alerted, not lost). That took a one-step fix after the first run exposed a Zoho Free-Edition limit (tags), plus replays of 2 transient Zapier Code-step errors.

  *Sources: report, leads section; `leadrouter/test_run.md`.*

- **Engineering hygiene:**
  - 163 OpsCore tests plus 11 LeadRouter Code-step tests;
  - idempotency keys (a replay returns the same job);
  - Celery retries with jitter;
  - an SSRF-guarded fetch;
  - TLS-pinned signed callbacks;
  - 30 written design decisions.

  *Sources: `opscore/docs/evidence/`, `opscore/DECISIONS.md`.*
