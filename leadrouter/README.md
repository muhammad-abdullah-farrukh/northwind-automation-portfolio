# LeadRouter (Zapier)

Northwind Digital's inbound-lead Zap:
- It validates each website lead, enriches it through **OpsCore** (`POST /v1/leads/enrich`) and scores it with **AI by Zapier**.
- It then routes the lead through **Paths**: hot, warm, cold or spam.
- The no-code flow decides *what happens*; OpsCore decides *what the data is*.

**Status: ran live on Zapier from 19 to 27 Oct 2026, inside the Zapier Pro trial.** See the [screenshots](#screenshots), the [video](../videos/Recording_Northwind2_trimmed.mp4) and [`test_run.md`](test_run.md).
- The Zap is "LeadRouter (draft)". Its last version is v4, which uses 26 of the trial's 30 steps; v3 and v4 only changed the OpsCore tunnel URL.
- All 15 test leads ended on their expected path, and three more leads came in through the Google Form.
- When the trial ended, the account dropped to Zapier's Free plan. That turns off Zaps that use premium features (Webhooks, Paths, multi-step), so LeadRouter and its form feeder no longer run.
- The contact form stopped accepting responses on 24 Oct 2026.

Every result in this file comes from a real run.

Step-by-step check with lead T01, done on the Free plan before the error handlers existed. The step numbers in this table are the draft's numbers at that time; the current numbering is under [Steps](#steps).

| Step | Built | Tested with lead T01 |
|---|---|---|
| 1 Catch Hook | yes | received (hook URL in git-ignored `.secrets/hook_url.txt`) |
| 2 Formatter Title Case | yes | "maya chen" → "Maya Chen" |
| 3 Code: prepare | yes | email `maya.chen@buffer.com`, website `https://buffer.com`, budget 40 + timeline 50 = base_score 90 |
| 4 Webhooks POST → OpsCore (`/v1/leads/enrich` via the tunnel) | yes; `X-API-Key` header value entered by the owner | HTTP 200: mx_valid, industry "Social media SaaS", rule_score 85, enrich_confidence 0.9 (cached domain) |
| 5 AI by Zapier (typed output fields: fit_score number, tier and recommended_service single-select, intent_summary, reply_draft) | yes | tier hot, fit_score 88, recommended AI automation, reply draft ending "Northwind Digital" |
| 6 Code: score | yes | final_score 89 = round(0.6×88 + 0.4×90), tier hot, deal "Buffer - AI automation" 7500, stage Qualification, first/last name split |
| 7 Zapier Tables: Create Record → "LeadRouter log" | yes | row written for T01 (tier hot, status logged) |
| 8 Paths: Hot / Warm / Cold / Spam, each `6. Tier` (Text) exactly matches its name | yes | T01 continues down Hot only; Warm, Cold and Spam correctly filter it out |
| Hot → Zoho Create/Update Contact (duplicate check Email) | yes | contact created |
| Hot → Zoho Create/Update Account (duplicate check Account Name; the deal's required Account lookup) | yes | account "Buffer" created |
| Hot → Zoho Create Deal (name, amount, closing date, stage `Qualification`, Account and Contact lookups by Record Id) | yes | deal "Buffer - AI automation" created |
| Hot → Slack Send Channel Message to #sales-hot (bot name LeadRouter, step-6 `slack_text`) | yes | one test message posted (owner approved) |
| Hot → Gmail Create Draft (to the lead, AI `reply_draft` body, from name Northwind Digital) | yes | one draft created, never sent (owner approved) |
| Warm → Zoho Create/Update Lead (duplicate check Email) | yes | lead created |
| Warm → Zoho Add Tag `nurture` (Entry ID = the lead's Record Id) | yes | tag added |
| Cold → Google Sheets Create Spreadsheet Row in "LeadRouter – Cold leads" (14 columns; Received at = step 7 created time) | yes | row written |
| Spam → Zapier Tables Update Record (status = "spam - no follow-up") | yes | test skipped on purpose: the only sample lead is hot, and testing would mislabel its log row |

Test records from T01 (Zoho contact/account/deal/lead, one Slack message, one Gmail draft, one Sheets row, one Tables row) are synthetic and can be deleted.

**Done in the trial (2026-10-19):**
- The OpsCore POST URL was updated to the current tunnel and re-tested (HTTP 200).
- Error handlers were added on the OpsCore step and on all four Zoho write steps (see [Error handling](#error-handling)). Their Slack steps were not test-run, because a test posts a real message; Zapier records them as "test skipped".

- v1 was published and the 15 test leads were run end to end (owner approved). Two failures turned up, and [`test_run.md`](test_run.md) has the details:
  - Zapier's transient Code-step "Pending" error hit 2 runs, which were replayed;
  - Zoho's "Add Tag" stopped working because the Zoho org dropped from its Enterprise trial to the Free Edition.
- v2 replaces the tag with Lead Status = "Contact in Future" on the warm lead.

**Also done in the trial (21–24 Oct):**
- The [Google Form and its feeder Zap](#google-form-northwind--contact-us) were built and published. Three form leads ran through LeadRouter (FORM-2 cold, FORM-3 hot, FORM-4 on the live error path; see [`test_run.md`](test_run.md)).
- v3 (21 Oct) and v4 (22 Oct) pointed the OpsCore step at a new tunnel after Docker restarts.
- The 13 screenshots and the video were captured and privacy-checked.
- The form was closed to responses on 24 Oct, after the videos.

Zapier flags Webhooks by Zapier and Paths as Pro features ("This Zap is using 3 Pro features"); a draft can be built and step-tested on Free, but publishing needs a paid plan or the trial. The trial also caps a Zap at 30 steps, which shaped the error handling below.
Zoho note: the org's currency locale is PKR (owner chose to keep it), so deal amounts such as 7500 are stored in PKR. They are illustrative values derived from the budget band.

### Zoho CRM deal stages
Read from the org's Deals → Stage picklist on 2026-10-03 (display value → API value, probability):
Qualification 10 · Needs Analysis 20 · Value Proposition 40 · Identify Decision Makers → `Id. Decision Makers` 60 ·
Proposal/Price Quote 75 · Negotiation/Review 90 · Closed Won 100 · Closed Lost 0 · Closed Lost to Competition 0.
Hot leads create deals in **Qualification** (`deal_stage` from the score step). Map the API value, not the label: they differ for "Identify Decision Makers".

| | |
|---|---|
| Zapier trial started | 2026-10-19 (Pro, 7 days; started by the owner) |
| Trial ends | 2026-10-27, as shown in Zapier Billing. The trial is set to "Downgrade to the Free plan", so nothing is charged, and Zaps that use premium features (Webhooks, Paths, multi-step) are turned off. The screenshots, the video and the test runs were all captured before then. |

## Flow

```
Catch Hook ─ Formatter ─ Code: prepare ─ Webhook: OpsCore enrich ─ AI by Zapier ─ Code: score ─ Tables: log ─ Paths
                                             └─ on error: Slack #ops-alerts + Tables row (status "error: OpsCore enrich failed")
Paths:
  Hot   → Zoho: contact (upsert) → Zoho: account (upsert) → Zoho: deal → Slack #sales-hot → Gmail: create DRAFT
  Warm  → Zoho: lead (upsert, Lead Status "Contact in Future")
  Cold  → Google Sheets: "LeadRouter – Cold leads" row
  Spam  → Tables: status = "spam - no follow-up"
(The Tables log row written before Paths already carries the tier, so only Spam updates its status.)
Each Zoho write step has an error handler → Slack #ops-alerts (alert only)
Feeder Zap: new row in the form's response sheet (Google Sheets) → Webhooks POST to the Catch Hook
```

## Error handling

Each handled step gets Zapier's error handler: a Success branch that carries on, and an Error branch that runs only when the step fails. Zapier turns autoreplay off for a step once it has a handler, so a failed run is not retried silently; the alert is the signal.

| Failing step | Error branch | Alert says (all post to `#ops-alerts` as the LeadRouter bot) |
|---|---|---|
| 4 OpsCore enrich | 5 Slack alert, 6 Tables row with status `error: OpsCore enrich failed` | lead ref and email, OpsCore's error message, "logged with status error and not routed" |
| 12 Zoho contact | 13 Slack alert | the account, deal, `#sales-hot` ping and Gmail draft were skipped |
| 14 Zoho account | 15 Slack alert | the contact was saved; the deal, ping and draft were skipped |
| 16 Zoho deal | 17 Slack alert | the contact and account were saved; the ping and draft were skipped |
| 21 Zoho lead (warm) | 22 Slack alert | the lead is in the log but not in Zoho |

Each alert quotes the failing step's own error message, so someone can finish the lead in Zoho by hand.

**The Zoho branches only alert.** They don't write a Tables row as well. The trial caps a Zap at 30 steps: the four Zoho alerts brought it to 27, and a Tables row on each would have needed 31. (v2 is at 26 after dropping the tag step.) The lead is already in the log from step 9, so the Slack alert is the record of the failure.

The Slack ping (18), Gmail draft (19), Sheets row (24) and Spam status update (26) have no handlers. Those failures show up in Zapier's run history and in its default error email.

**Code-step platform errors.** In the test run, Zapier's own Code runtime failed 2 runs with "The function is currently in the following state: Pending", before our Python ran. The Code steps have no handlers and account-level Autoreplay is off, so such a run stays failed until it is replayed from Zap history (both were).

## Steps

Numbers match the Zap editor. Zapier numbers error-branch steps in sequence, so 5–6 are the OpsCore error branch and the main line resumes at 7.

| # | App / action | Configuration |
|---|---|---|
| 1 | Webhooks by Zapier: Catch Hook | Lead fields: `lead_ref`, `name`, `email`, `company`, `website`, `budget`, `service`, `timeline`, `message`, `source` |
| 2 | Formatter: Text → Title Case | `name` |
| 3 | Code by Zapier: Run Python | [`code/prepare_lead.py`](code/prepare_lead.py): normalized email, domain, free-mail flag, `dedupe_key = sha256(email)`, `base_score` (budget + timeline), spam heuristics |
| 4 | Webhooks by Zapier: POST | `https://<tunnel>/v1/leads/enrich`. JSON body: email, website, company, name. Headers: `X-API-Key` (OpsCore `zapier` key), `Idempotency-Key: {{dedupe_key}}`. Error handler attached. |
| 5–6 | *Error branch of 4:* Slack alert, Tables row | See [Error handling](#error-handling) |
| 7 | AI by Zapier: Analyze and Return Data | Instructions: [`../opscore/prompts/lead_icp_v1.md`](../opscore/prompts/lead_icp_v1.md). Output fields: `fit_score` (number), `tier`, `intent_summary`, `recommended_service`, `reply_draft` |
| 8 | Code by Zapier: Run Python | [`code/score_lead.py`](code/score_lead.py): `final_score = round(0.6 × AI + 0.4 × base)`, with a fallback to base when the AI output is unusable; the tier; Slack text; Zoho deal fields |
| 9 | Zapier Tables: Create Record | Table "LeadRouter log", one row per lead, with the tier as a colour-coded field. It has to come before Paths, because Paths must be the last step. |
| 10 | Paths | Hot (tier = hot), Warm (tier = warm), Cold (tier = cold), Spam (tier = spam) |
| 11–19 | Hot path | 12 Zoho contact, 14 account, 16 deal (13, 15, 17 are their error alerts), 18 Slack `#sales-hot`, 19 Gmail draft |
| 20–22 | Warm path | 21 Zoho Create/Update Lead with Lead Status "Contact in Future" (22 is its error alert) |
| 23–24 | Cold path | 24 Google Sheets row |
| 25–26 | Spam path | 26 Tables status update |

**Changes from the original design:**
- **CRM:** Zoho CRM replaces HubSpot, because HubSpot's sign-up required a company website.
- **Warm-lead nurture flag:** first Zoho's "Add Tag: nurture", replacing the Mailchimp/Kit branch. Since v2 it is Lead Status = "Contact in Future", because tags need a paid Zoho edition (found in the test run).
- **AI output:** the AI step returns typed output fields instead of a JSON string. The score step still validates them and has a fallback.

## Google Form: "Northwind – Contact us"

The choice labels must match exactly, because the score step maps them to points.

| Question | Type | Choices |
|---|---|---|
| Full name | Short answer (required) | |
| Work email | Short answer (required, email validation) | |
| Company | Short answer | |
| Website | Short answer | |
| Budget | Multiple choice (required) | `Under $1k`, `$1k-2k`, `$2k-5k`, `$5k-10k`, `$10k+` |
| Service | Multiple choice (required) | `AI automation`, `Zapier / n8n workflows`, `CRM setup`, `Marketing automation`, `Other` |
| Timeline | Multiple choice (required) | `ASAP`, `Within 1 month`, `1-3 months`, `3+ months`, `Just exploring` |
| Message | Paragraph | |

**How a response reaches LeadRouter:**
- Responses land in the form's linked response sheet.
- A second Zap, "LeadRouter feeder: Google Form → Catch Hook", triggers on each new row (Google Sheets, New Spreadsheet Row).
- It POSTs JSON to LeadRouter's Catch Hook with:
  - `lead_ref` = "FORM-" + the sheet's row number;
  - the eight answers as `name`, `email`, `company`, `website`, `budget`, `service`, `timeline` and `message`;
  - `source` = `google-form`.
- Google's change notification is the slow part: FORM-3's LeadRouter run started about 2 min 40 s after Submit.

The form was test-only. It stopped accepting responses on 24 Oct 2026, so no outside submission can reach Zoho, Slack or Gmail. Its responder link and the form, sheet and Zap IDs are not published here.

## Testing

- `python -m unittest discover -s tests -v` runs both Code steps exactly as Zapier does (`input_data` in, `output` out).
- [`test_leads.json`](test_leads.json) holds 15 synthetic leads: 5 hot, 4 warm, 3 cold, 2 spam, and 1 error. The error lead is `T15`, a double-dot email that OpsCore rejects with a 422.
- `send_test_leads.ps1` posts them to the Catch Hook. It reads the hook URL from git-ignored `.secrets/hook_url.txt`.
- The contact names are fictional. The company domains are public websites, used only so OpsCore has a real homepage and MX record to check. No affiliation is implied, and nothing is ever emailed: the Zap only creates Gmail **drafts**.

## Screenshots

Captured on 2026-10-21, while the Zap was live. Each one was checked for personal data (see `../opscore/docs/evidence/privacy_check.txt`).

| Screenshot | Shows |
|---|---|
| [Canvas, whole Zap](../docs/screenshots/leadrouter_canvas.png) | All 26 steps of v3: main line, the OpsCore error branch, the four paths and the Zoho error alerts |
| [Main line](../docs/screenshots/leadrouter_mainline.png) | Steps 1–8, readable: Catch Hook → Formatter → Code → OpsCore POST (Success and Error branches) → AI → Code |
| [AI step](../docs/screenshots/leadrouter_ai_step.png) | T01: the prompt with mapped fields, and the typed output (tier hot, fit 88, reply draft, intent summary) |
| [Score step](../docs/screenshots/leadrouter_score_step.png) | T01: final score 89 = 0.6 × AI + 0.4 × base, tier, Slack text and Zoho deal fields |
| [Paths rule](../docs/screenshots/leadrouter_paths_rule.png) | The Hot path runs only when `8. Tier` exactly matches `hot` |
| [Run trace, hot lead](../docs/screenshots/leadrouter_run_trace_hot.png) | T01's run on 19 Oct (v1): the route it took, in green, down the Hot path only |
| [Log table](../docs/screenshots/leadrouter_log_table.png) | The LeadRouter log, colour-coded by tier, including the form lead FORM-2 |
| [Slack `#sales-hot`](../docs/screenshots/leadrouter_slack_sales_hot.png) | The five hot-lead pings from the 19 Oct test run |
| [Slack `#ops-alerts`](../docs/screenshots/leadrouter_ops_alert.png) | T15: OpsCore rejected the email, and the lead was logged as an error and not routed |
| [Gmail draft](../docs/screenshots/leadrouter_gmail_draft.png) | The AI reply drafted for T01, never sent |
| [Google Form](../docs/screenshots/leadrouter_google_form.png) | The contact form's questions and choices |
| [Zoho deal (Zapier step 16)](../docs/screenshots/leadrouter_zoho_deal_step.png) | The deal sent to Zoho for T01: Deals module, "Buffer - AI automation", 7500, stage Qualification, linked contact and account |
| [Hot-lead collage](../docs/screenshots/leadrouter_hot_lead_collage.png) | One hot lead's three outputs: the `#sales-hot` ping, the Gmail draft and the Zoho deal |

The Zoho deal is shown from the Zapier side (the data step 16 sent), because Zoho's web app would not load on 21–22 Oct.

## Video

[`../videos/Recording_Northwind2_trimmed.mp4`](../videos/Recording_Northwind2_trimmed.mp4) is 46 s with no voice-over. It was recorded on 22 Oct 2026 and follows the real FORM-3 run: the form, the run's route, the AI and score steps, the Zoho deal step, `#sales-hot`, the Gmail draft, the log table and `#ops-alerts`. The shot list and what was cut or blurred are in [`../docs/video_scripts.md`](../docs/video_scripts.md), section 3.

[`../videos/Recording_Northwind_trimmed.mp4`](../videos/Recording_Northwind_trimmed.mp4) is a 21 s companion clip, cut from the first take on 22 Oct. It shows three screens: the whole Zap at v4, Zapier's Zap history (runs from 19–21 Oct), and the form feeder Zap (Google Sheets New Spreadsheet Row → Webhooks POST).
