# 60-second demo videos: shot scripts

**How we record.** Abbi records the screen with **Win + Alt + R** (Xbox Game Bar) and adds an optional voice-over, while Claude drives the browser through the shots below.
- **Before each take:**
  - close unrelated tabs and silence notifications;
  - put Chrome in **full-screen (F11)**, so the tab titles and address bar (account email, sheet and Zap IDs) aren't recorded;
  - keep account menus and avatars off screen.
- Only show synthetic data that is already in the system. Every number said aloud must come from the eval report, the P5 acceptance run or `leadrouter/test_run.md`.
- **Schedule:** record all takes by 24 Oct (LeadRouter on 22 Oct, InvoiceIQ on 23 Oct, OpsCore by 24 Oct), and don't restart Docker until all three are accepted. Abbi watches every take and logs it in `opscore/docs/evidence/privacy_check.txt` before it is used anywhere.

## 1. InvoiceIQ (n8n): "an emailed invoice to an approved ledger row, with a human in the loop"
**Recorded 23 Oct 2026, accepted and logged in `opscore/docs/evidence/privacy_check.txt`.** The final cut is `videos/Recording_Northwind3_trimmed.mp4`.
- It runs 62 s with no voice-over yet and follows the table below.
- The Slack Review form isn't opened, because BH-03890's approval finished on 19 Oct. The card and the "approved with corrections" message show the result.
- The Q&A agent's answer was a new run during the take. The local model took about 30 s, and that wait is cut, so a voice-over should say the reply takes about half a minute.


| Time | Screen | What happens / voice-over |
|---|---|---|
| 0–6 s | n8n "1 Intake" canvas | "Supplier invoices arrive by email or an upload form. Each PDF gets its own run." |
| 6–14 s | "2 Process invoice" canvas, zoomed to the left half | "OpsCore extracts and validates the invoice, then calls back with an HMAC-signed result, and n8n checks the signature." |
| 14–24 s | Same canvas, right half (Route, Store, Exceptions) | "Confident invoices are filed automatically. Uncertain ones go to Slack. Duplicates are skipped, and failures alert ops." |
| 24–36 s | Slack #finance-approvals: the BH-03890 card, the **Review invoice** form, the "approved with corrections" message | "This invoice's own maths was wrong. A reviewer corrects the total in Slack, and the corrected value is what gets stored." |
| 36–44 s | Google Sheet "Northwind Ledger", Invoices and Exceptions tabs | "Every filed invoice lands in the ledger. The duplicate and the failed scan are on the Exceptions tab." |
| 44–56 s | n8n "4 Finance Q&A agent" chat, asking: *"What did Bluefin Hosting bill us for?"* | "A local model answers from the ledger and cites the invoice number." |
| 56–60 s | Slack #ops-alerts error message | "And when something fails, ops hears about it with a link to the run." |

## 2. OpsCore (Python): "the engine, tested"
**Recorded 24 Oct 2026, accepted and logged in `opscore/docs/evidence/privacy_check.txt`.** The final cut is `videos/Recording_Northwind4_trimmed.mp4`.
- It runs 59 s with no voice-over yet and follows the table below.
- Everything was shown in the browser. The test and eval-gate shots are captured output from the 24 Oct 10:37 runs, not commands typed live, and each page's header says so: `docker compose exec api python -m pytest` gave 163 passed in 9.61 s, and `run_evals ci` gave CI EVAL GATE PASS.


| Time | Screen | What happens / voice-over |
|---|---|---|
| 0–8 s | `docs/architecture.png` | "Zapier and n8n hand the hard part to one Python service." |
| 8–18 s | Swagger UI at `http://127.0.0.1:8000/docs` | "It has lead enrichment, async invoice jobs with signed callbacks, and human review that becomes eval ground truth." |
| 18–30 s | Terminal: `docker compose exec api pytest -q`, ending in "163 passed" | "163 tests, with no model and no network." |
| 30–48 s | `opscore/evals/report.md`: the test-slice tables | Read the measured numbers from the report: field accuracy, documents fully exact, and wrong money values that reached `done`, each with its `n`. |
| 48–60 s | `.github/workflows/ci.yml` and `run_evals ci` passing locally | "CI replays the recorded model answers and fails if any score moves." |

## 3. LeadRouter (Zapier): "a website lead, scored and routed in under a minute"
**Recorded 22 Oct 2026, accepted and logged in `opscore/docs/evidence/privacy_check.txt`.** The final cut is `videos/Recording_Northwind2_trimmed.mp4`.
- It runs 46 s with no voice-over yet. It follows the real FORM-3 run: the form's confirmation page, the run's route, the AI step, the score step, the Zoho deal step, `#sales-hot`, the Gmail draft, the log table and `#ops-alerts`.
- The raw take missed `#sales-hot` and the log table, so those are stills from screenshots taken during the FORM-3 run.
- The Gmail draft still is T01's draft from the 19 Oct test run, because FORM-3's draft was never captured.
- `#ops-alerts` shows both the T15 alert and the FORM-4 alert, the error path running live during the re-take.

Record by 22 Oct (the Zapier trial ends 27 Oct, and premium Zaps stop then). The take submits **one new synthetic hot lead**, which creates one Zoho contact, account and deal, one `#sales-hot` message and one Gmail **draft**. That is expected.

**Privacy setup before the take (all of it is required):**
- Chrome in **full-screen (F11)**. This hides the tab strip, whose Gmail tab title contains the account email, and the address bar, which shows the form, Zap and sheet IDs.
- Open Gmail on a search for `subject:"your enquiry to Northwind Digital"`. **Never show the Drafts list**, because it holds personal drafts.
- Open the draft in full-screen compose, so only the To, Subject and body show.
- Never open the feeder Zap's step 2 (it holds the hook URL) or any Share or Publish dialog of the form.
- Keep the Zapier, Google, Slack and Zoho account menus closed. In Zoho, zoom into the deal record.
- **Pre-flight:** the tunnel matches LeadRouter step 4, `/healthz` returns 200, and the Docker stack is not restarted.
- Abbi watches the take before using it, and logs it in `opscore/docs/evidence/privacy_check.txt`.

**Synthetic hot lead to type:** a fictional name and company at a public SaaS domain (as T01–T05 used), budget "$5k-10k", service "AI automation", timeline "ASAP", and a one-line concrete problem.

**Re-take plan (decided 22 Oct, after the first take recorded the wrong tab):**
- **No new submission.** The take walks through the real **FORM-3** run from 22 Oct, 05:26–05:29.
  - Show the form filled with the same answers, not resubmitted.
  - Then show the run it produced, the `#sales-hot` ping, the Zoho deal step and the log row.
- **Before recording:** Claude loads the form in the tab it will drive. Abbi confirms that this tab is the one in front (clicking it if not), presses F11, then Win+Alt+R.
- **Gmail:** show the draft only if Chrome is in full screen. Otherwise show the run's green route ending at "19. Create Draft".

| Time | Screen | What happens / voice-over |
|---|---|---|
| 0–8 s | The "Northwind – Contact us" form, filled in, then **Submit** | "A prospect fills in the contact form." |
| 8–16 s | LeadRouter's Zap history, with the new run at the top | "Zapier picks it up, checks it in Python, and asks OpsCore to enrich it." |
| 16–28 s | The run view: AI step output (tier, fit score, reply draft), then the score step (final score = 0.6 × AI + 0.4 × rules) | "An AI step scores the fit, and code blends that with a rules score into a tier." |
| 28–36 s | Slack `#sales-hot`: the new ping | "Hot leads ping sales straight away…" |
| 36–44 s | The Zoho deal record. If Zoho's web app still won't load, show the run's step 16 instead (the Deals data sent to Zoho). | "…become a deal in the CRM…" |
| 44–52 s | The Gmail draft in full-screen compose | "…and get a reply drafted, never sent automatically." |
| 52–60 s | The log table, colour-coded by tier, then the T15 alert in `#ops-alerts` | "Every lead is logged. In the 15-lead test run every one landed on its expected path, and a bad email was alerted, not lost." |
