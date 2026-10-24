# InvoiceIQ (n8n)

Northwind Digital's accounts-payable inbox, automated:
- Supplier invoices arrive by **email** (Gmail) or through an **upload form**.
- **OpsCore** extracts and validates each one asynchronously, then sends back an HMAC-signed callback.
- Confident invoices are filed automatically. Uncertain ones go to a **Slack review form**. Duplicates are skipped, and failures alert **#ops-alerts**.
- Filed invoices land in **Postgres**, in the **"Northwind Ledger" Google Sheet**, and in a **pgvector** index.
- A local **finance Q&A agent** answers questions and cites invoice numbers.

Everything runs locally: n8n 2.40 in Docker, with OpsCore's Postgres 16 + pgvector and Ollama (qwen3 4B + nomic-embed-text).
All invoices are synthetic, with fictional vendors. Every result below comes from a real run.

**Status:** done. All four workflows are built, published and accepted on 2026-10-19 (see [Acceptance run](#acceptance-run-p5-done-when)): 10 emailed invoices, Slack approval, the error workflow, and an agent that answers with cited invoice numbers.

## Workflows

| # | Workflow | What it does |
|---|---|---|
| 1 | **Intake** | Gmail trigger (every minute; `has:attachment filename:pdf -label:invoices`) and an upload form. Splits each message or submission into one item per PDF, starts **2** once per PDF without waiting, then labels the email `invoices` so it is never read twice. |
| 2 | **Process invoice** | SHA-256 of the file → `POST /v1/jobs` (multipart, `callback_url` = this execution's resume URL, `Idempotency-Key` per execution) → **Wait** for the callback → rebuild `timestamp.raw_body` and check the HMAC-SHA256 plus a 5-minute freshness window → ledger lookup → route (below). |
| 3 | **Error handler** | Error Trigger for workflows 1, 2 and 4: one row in `finance.errors` and a message to **#ops-alerts** with a link to the failed execution. |
| 4 | **Finance Q&A agent** | Chat trigger → AI Agent (qwen3 4B on Ollama, Postgres chat memory). Tools: `query_ledger` (workflow **4a**), `search_invoices` (pgvector), `pending_reviews` (OpsCore `GET /v1/jobs?status=needs_review`). |
| 4a | **safe_sql tool** | The agent's SQL tool. It allows one `SELECT` only, refuses write keywords, adds `LIMIT 50`, and runs as the read-only `finance_agent` role. |

### Routing in workflow 2

```
signed callback ──(bad signature / stale / no callback in 20 min)──► exception: failed ─► Stop and Error ─► workflow 3
      │
  ledger lookup (same vendor + invoice number already filed?) and vendor history
      │
   Route ─┬─ auto-approve   OpsCore status "done" (validation clean, confidence ≥ 0.85)
          ├─ needs review   Slack #finance-approvals form: Approve / Approve with corrections / Reject
          │                    approved ─► POST /v1/jobs/{id}/review (human-checked data kept as eval ground truth)
          ├─ duplicate      OpsCore duplicate_of (vendor + number + total) or the ledger lookup
          └─ failed         OpsCore could not extract (e.g. a scan with no text layer)

store (auto-approved + approved):
  one SQL statement: finance.invoices + finance.line_items + finance.intake_events("stored")
  ├─ Slack summary in #finance-approvals (with anomaly flags)
  ├─ "Northwind Ledger" ▸ Invoices row
  └─ pgvector: invoice summary + line items embedded with nomic-embed-text

exceptions (duplicate, rejected, failed):
  finance.intake_events row ─ "Northwind Ledger" ▸ Exceptions row ─ failed: Stop and Error / others: Slack note
```

**Anomaly flags.** These are informational: they appear in Slack and the sheet but never block an invoice.
- A new vendor, with no earlier invoices in the ledger.
- A total at least 3× the vendor's average in the same currency.
- A due date before the invoice date.
- An invoice date in the future.

## Data

The schema lives in the OpsCore Postgres. The SQL is in [`sql/`](sql/), and each file can be re-run safely.

| Table | Written by | Read by |
|---|---|---|
| `finance.invoices`, `finance.line_items` | `finance_writer` (workflow 2) | `finance_agent` (agent SQL) |
| `finance.intake_events`: exactly one outcome per file (`stored` / `duplicate` / `rejected` / `failed`) | `finance_writer` | none |
| `finance.errors` | `finance_writer` (workflow 3) | none |
| `finance.invoice_embeddings` (`vector(768)`, HNSW cosine index) | `finance_writer` | `finance_writer` (fixed vector-store queries) |
| `finance.agent_chat_memory` | `finance_writer` | `finance_writer` |

**Roles**
- `finance_writer` can only insert and update in `finance`.
- `finance_agent` is the role that LLM-written SQL runs as:
  - `default_transaction_read_only = on`;
  - `statement_timeout = 5s`;
  - `SELECT` on `invoices` and `line_items` only.
- The semantic search and the chat memory never run LLM-written SQL, so they use the writer role with n8n's fixed, parameterised queries. The read-only role cannot run the `CREATE … IF NOT EXISTS` statements those nodes issue on start-up.
- Every Postgres node passes its values as **one `jsonb` parameter**, so commas or quotes inside invoice data can never break a query.

**Google Sheet: "Northwind Ledger"**
- **Invoices** columns: Received at, Invoice no, Vendor, Invoice date, Due date, Currency, Subtotal, Tax, Total, Status, Confidence, Approved by, Source, Anomalies, OpsCore job.
- **Exceptions** columns: Received at, File, Outcome, Detail, Duplicate of, OpsCore job, Source.

## Design notes

- **One execution per PDF.**
  - An n8n Wait node has one resume URL per *execution*, not per item. So workflow 1 hands every PDF to its own run of workflow 2.
  - With ten PDFs in one execution, the first callback would resume it and the other nine would get 409s. OpsCore treats a 4xx as permanent and does not retry it (OpsCore D28).
- **The signature is checked over the raw body.** The Wait node keeps the raw bytes (`rawBody`), and the HMAC is computed over `"<X-OpsCore-Timestamp>.<raw body>"`, exactly what OpsCore signed (OpsCore D26). A parsed-and-re-serialised body could reorder keys.
- **Two duplicate checks.**
  - OpsCore compares the normalised vendor, invoice number and total within this API key's jobs.
  - Workflow 2 also looks for the same vendor and invoice number in `finance.invoices`, which catches a re-sent invoice even after OpsCore's history is gone.
- **Publishing (n8n 2.x).**
  - Live (non-manual) executions call the **published** version of a sub-workflow, and an error workflow must be published before it runs.
  - Workflows 1, 2, 3 and 4a are therefore published together, after the last edit.
- **Sheet append race (found in the acceptance run, fixed).**
  - Six auto-approved invoices finished within 5 seconds of each other, and all six "Append to Northwind Ledger" steps reported success. Only the last two rows survived.
  - n8n's Google Sheets node works out the next empty row itself and then writes to that row, so parallel runs overwrote each other. Even with its "Use Append" option, it pins the append to a row number it computed itself; a parallel retest of that option still lost 1 of 4 rows.
  - **Fix:** both sheet steps are now direct `values.append` calls with `insertDataOption=INSERT_ROWS`, so Google inserts each row at the end of the table itself.
  - **Proof:** 8 appends run in parallel by 8 separate executions (the same fan-out as production) all landed, 8/8.
  - Postgres was never affected, because each invoice is one transaction.
- **Retries.** Every Google and Slack call retries 5 times, 3 s apart. During the build, connections from this machine to `*.googleapis.com` dropped for several minutes at a time.

## Setup

1. Apply [`sql/001_finance_schema.sql`](sql/001_finance_schema.sql) (it sets the role passwords from psql variables), then [`sql/002_agent_tables.sql`](sql/002_agent_tables.sql).
2. Create these n8n credentials. The owner types every secret into n8n; none are stored in this repo.

   | Credential | Type | Notes |
   |---|---|---|
   | OpsCore n8n key | Header Auth | `X-API-Key` |
   | OpsCore callback HMAC | Crypto | Same value as OpsCore's `CALLBACK_HMAC_SECRET` |
   | Gmail - InvoiceIQ | Gmail OAuth2 | Google Cloud OAuth client, test user = the owner |
   | Sheets - InvoiceIQ | Google Sheets OAuth2 | Same OAuth client |
   | Postgres - finance writer | Postgres | `host.docker.internal:5433`, user `finance_writer` |
   | Postgres - finance agent (read-only) | Postgres | User `finance_agent` |
   | Ollama (local) | Ollama | `http://host.docker.internal:11434` |
   | Slack - InvoiceIQ | Slack API | Bot token; scopes `chat:write`, `channels:read`; bot invited to `#finance-approvals` and `#ops-alerts` |

3. Import the workflow JSON files from [`workflows/`](workflows/), select the credentials, and publish workflows 3, 2, 4a and then 1. Workflow 4 runs in the editor chat; publish it only for the hosted chat.

## Smoke test

This ran on 2026-10-05 through the upload form in test mode, with the Slack steps switched off. It used spare eval invoices rather than the acceptance set, so that set still starts clean in OpsCore.

| File | OpsCore job | OpsCore result | n8n route | Outcome |
|---|---|---|---|---|
| inv_030.pdf | job_01M45S2SJ0AXF2Z4N9ZF0X3290 | done, confidence 1.0 | auto-approve | Stored: 1 invoice + 2 line items; Invoices row; embedding (768 dims) |
| inv_029.pdf (bad totals) | job_01M45S2SM73HY3K420N0EZ5E05 | needs_review, confidence 0.72 | needs review | No reviewer (Slack off) → recorded as *rejected (no answer)*; Exceptions row |
| smoke_031_scan.pdf (image only) | job_01M45S2SQ056NCHW10HAV4CK12 | failed: no text layer | failed | Exceptions row; execution stopped with the OpsCore reason |
| inv_037.pdf (same invoice as inv_030) | job_01M45S8HNVH902623PVNM9GJGE | done, `duplicate_of` job_…3290 | duplicate | Skipped; Exceptions row |

- All four callbacks were delivered at the first attempt (HTTP 200), and every signature verified.
- Extraction times reported by OpsCore were 13.2 s (inv_030), 25.0 s (inv_029, which includes the repair pass) and 6.6 s (inv_037).
- **Agent check** against this one-invoice ledger: asked *"What was invoice BA009349 for, and are any invoices still waiting for review?"*, it called `search_invoices` and `pending_reviews`. It answered that BA009349 was data connector setup and a dashboard build from Brightline Analytics LLC, USD 2505.78, and that MLM-7852 (Maple Leaf Media Inc., CAD 6282.32) is waiting for review.
- **Found during the smoke test:**
  - The Crypto node drops binary data, so the PDF is re-attached before the upload.
  - A "past due" anomaly flag fired on every synthetic invoice, so it was removed.
  - The agent's SQL tool needs workflow 4a to be published.

**Smoke-test data was cleared before the acceptance run** (on 2026-10-19, with the owner's approval):
- its finance rows, embedding and chat memory;
- the 4 smoke OpsCore jobs and their idempotency records;
- rows 2 onward of both sheet tabs.

The ledger below therefore holds only the acceptance set.

## Acceptance run (P5 "done when")

Run on 2026-10-19. Intake (workflow 1) was published at 13:53:00 UTC, and the test set was emailed to the owner's own Gmail through a temporary helper workflow.
- **13:54:13:** 9 emails sent.
- **13:58:56:** the duplicate (inv_023) sent, once its original had been filed.

Gmail polling picked up the 9 emails at 13:55:23. Each PDF ran as its own execution of workflow 2. Every signed callback was delivered at the first attempt (HTTP 200) and verified.

| File | Invoice | OpsCore result (extraction time) | Route | Outcome |
|---|---|---|---|---|
| inv_011.pdf | MLM-6091, Maple Leaf Media, CAD 3519.23 | done, 1.0 (11.4 s) | auto-approve | Stored |
| inv_012.pdf | BA006012, Brightline Analytics, USD 2365.25 | done, 1.0 (11.2 s) | auto-approve | Stored |
| inv_013.pdf | BH-03890, Bluefin Hosting, GBP | needs_review, 0.72 (28.9 s): `subtotal + tax = 1657.73 but total is 1667.73` | Slack review | **Approved with corrections**: total 1667.73 → 1657.73 |
| inv_014.pdf | INV-2805, Copperleaf Print, USD 747.13 | done, 1.0 (20.8 s) | auto-approve | Stored |
| inv_015.pdf | RE-26-8437, Nordlicht Software, EUR 257.12 | done, 1.0 (14.4 s) | auto-approve | Stored |
| inv_016.pdf | ICS/1554, Indus Cloud Services, PKR 258111.60 | needs_review, 0.97 (41.0 s): line 1 `qty x unit_price = 5685.00 but amount is 56850.00` (the unit price was misread) | Slack review | **Approved as extracted**: the total matches the PDF |
| inv_017.pdf | MLM-8837, Maple Leaf Media, CAD 960.39 | done, 1.0 (10.2 s) | auto-approve | Stored |
| inv_018.pdf | BA004981, Brightline Analytics, USD 1989.89 | done, 1.0 (9.4 s) | auto-approve | Stored |
| inv_019_scan.pdf | (image-only scan) | failed: no text layer | failed | Exceptions row; workflow 3 wrote `finance.errors` and posted to **#ops-alerts** |
| inv_023.pdf | MLM-6091 again (a different PDF of the same invoice) | done, `duplicate_of` the inv_011 job (6.0 s) | duplicate | **Skipped**; Exceptions row and a note in #finance-approvals |

**Ledger after the run**
- `finance.invoices`: 8 invoices.
  - 6 `auto_approved`.
  - 1 `approved`.
  - 1 `approved_with_edits`, with the edit `{"total": {"from": 1667.73, "to": 1657.73}}` in `finance.intake_events`.
- `finance.intake_events`: 10 outcomes (8 stored, 1 duplicate, 1 failed).
- 8 embeddings, 1 row in `finance.errors`.
- The sheet was **not** complete after the run. "Exceptions" had its 2 rows, but "Invoices" had only 4 of the 8 (see "Sheet append race" below). The 4 lost rows were written back on 2026-10-19 from the exact row values the original executions computed, so the sheet now has all 8.
- OpsCore stored both human reviews as eval ground truth (`job_reviews`), so those two jobs moved to `reviewed`.

**The anomaly flag in practice:** "new vendor" fired on the first invoice from each of the 6 vendors. It did not fire on MLM-8837 or BA004981, because by then the same vendor already had an invoice in the ledger.

**Slack reviews:** the two review forms were submitted through the **Review invoice** buttons in #finance-approvals, by Claude, on the owner's instruction. The decisions were:
- BH-03890: approve, with the total corrected to the invoice's own arithmetic.
- ICS/1554: approve as extracted, because the total is right and only a line item was misread.

### Finance Q&A agent: 5 test questions

These ran in the editor chat on qwen3 4B, local through Ollama. Expected answers were computed with SQL first. Round 1 used the original prompt.
- Round 1 exposed two prompt gaps:
  - It did not explain the `approved_by` values.
  - It did not insist on currency codes.
- Both were added to the system prompt, and **round 2** re-ran the same 5 questions in a fresh session.

| # | Question | Expected (SQL) | Round 1 | Round 2 |
|---|---|---|---|---|
| 1 | Which invoices do we have from Maple Leaf Media, and what are their totals? | MLM-6091 CAD 3519.23; MLM-8837 CAD 960.39 | Correct; cites [MLM-6091] [MLM-8837], but labelled the amounts "$" | Correct, with "CAD". (Its SQL still did not select the currency column, so "CAD" was not grounded in the tool result.) |
| 2 | How much have we been invoiced in total, per currency? List the invoices behind each total. | CAD 4479.62 · EUR 257.12 · GBP 1657.73 · PKR 258111.60 · USD 5102.27 | Correct totals and invoice lists; "$" prefixes | Correct, with currency codes; all 8 invoices cited |
| 3 | Which invoice has the earliest due date, and when was it due? | INV-2805, 2026-02-28 | Correct, cites [INV-2805] | Correct, cites [INV-2805] |
| 4 | What did Bluefin Hosting bill us for? | Load balancer 2 × 37.09, managed backups 8 × 31.72, premium support 5 × 210.70 | Correct via `search_invoices`, cites [BH-03890], GBP 1657.73 | Correct via `search_invoices`, with all three lines and their quantities and prices |
| 5 | Which invoices were approved by a person in Slack instead of automatically, and which one was corrected? | BH-03890 (approved_with_edits), ICS/1554 (approved) | **Partial**: only [BH-03890] (its SQL filtered on `approved_with_edits`) | Correct: [BH-03890] with edits, [ICS/1554] without |

**Scores**
- Round 1: 4 of 5 fully correct, 1 partial.
- Round 2: 5 of 5 correct.
- Every answer in both rounds cited invoice numbers.
- Tools used: `query_ledger` (as the read-only `finance_agent` role) for Q1–3 and Q5, and `search_invoices` (pgvector) for Q4.

### P5 "done when" checklist
- [x] 10 invoices processed by email: 8 filed, 1 duplicate, 1 failure.
- [x] The duplicate was skipped (inv_023 → MLM-6091).
- [x] The low-confidence invoice was approved via Slack (BH-03890, confidence 0.72, approved with a corrected total). ICS/1554 was approved too.
- [x] The agent answered 5 test questions, citing invoice numbers.
- [x] The error workflow fired: the inv_019 scan produced a `finance.errors` row and an #ops-alerts message.

**Operational note:** the Google OAuth client is in *Testing* status, so Google expires its refresh tokens after 7 days. The Gmail and Sheets credentials had to be reconnected before this run. Publishing the client needs a real home page and privacy-policy domain.

## Files

- `workflows/`: the exported workflow JSON (`1_intake`, `2_process_invoice`, `3_error_handler`, `4_finance_agent`, `4a_safe_sql_tool`). Credentials are referenced by name and id only, and instance metadata (owner, sharing, trigger state) has been stripped.
- `sql/`: the finance schema and the agent tables.
- `test_invoices/`: the 10-invoice acceptance set: 8 distinct invoices, 1 duplicate and 1 image-only scan.
- `p4_job_callback_test.json`: the P4 signed-callback test workflow.
