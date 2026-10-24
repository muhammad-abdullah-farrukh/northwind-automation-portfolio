# LeadRouter end-to-end test run

**Setup.**
- Zap "LeadRouter (draft)" was published as version v1 on 2026-10-19, inside the Zapier Pro trial.
- The 15 leads in [`test_leads.json`](test_leads.json) were posted by `send_test_leads.ps1`, 5 s apart.
- Zapier logged the triggers from 21:16:45 to 21:18:01 (America/Los_Angeles, as Zapier shows it).

**Sources:**
- Zapier's Zap history (status, task count and the failing step's error for each run);
- the "LeadRouter log" table (tier, scores and status for each lead);
- Zoho CRM's Leads list.

## Results, run by run

| Lead | Expected | Zapier run | Tier logged | What happened |
|---|---|---|---|---|
| T01 | hot | Successful, 9 tasks | hot (AI 88, base 90) | Zoho contact + account + deal, Slack `#sales-hot`, Gmail draft |
| T02 | hot | Successful, 9 tasks | hot (AI 88, base 90) | same as T01 |
| T03 | hot | Successful, 9 tasks | hot (AI 87, base 90) | same as T01 |
| T04 | hot | Successful, 9 tasks | hot (AI 91, base 80) | same as T01 |
| T05 | hot | Successful, 9 tasks | hot (AI 85, base 100) | same as T01 |
| T06 | warm | **Errored**, 3 tasks | not logged | Step 8 (Code: score) failed with a Zapier platform error: "The operation cannot be performed at this time. The function is currently in the following state: Pending" |
| T07 | warm | **Errored**, 5 tasks | warm (AI 62, base 40) | Zoho lead created; step 23 (Zoho Add Tag) failed: "your edition doesn't support this feature" |
| T08 | warm | **Errored**, 5 tasks | warm (AI 52, base 40) | same as T07 |
| T09 | warm | **Errored**, 5 tasks | warm (AI 74, base 55) | same as T07 |
| T10 | cold | Successful | cold (AI 8, base 5) | Google Sheets "Cold leads" row |
| T11 | cold | **Errored**, 0 tasks | not logged | Step 3 (Code: prepare) failed with the same "Pending" platform error |
| T12 | cold | Successful | cold (AI 15, base 15) | Google Sheets row |
| T13 | spam | Successful | spam (AI 0, base 100) | log status set to "spam - no follow-up" (spam reasons: links in the message, spam phrases) |
| T14 | spam | Successful | spam (AI 0, base 100) | log status set to "spam - no follow-up" (spam reasons start "disposable email domain, name look…") |
| T15 | error | Handled error | (blank) | OpsCore rejected the double-dot email. The error branch posted to `#ops-alerts` and logged status "error: OpsCore enrich failed". |

**Replays on v2 (2026-10-19 21:41–21:42).** These used Zapier's Replay after the fix described under "Failures found" below.

| Lead | Zapier run | Tier logged | What happened |
|---|---|---|---|
| T11 | Successful | cold (AI 12, base 15) | Google Sheets row |
| T06 | Successful | warm (AI 78, base 55) | Zoho lead created with Lead Status "Contact in Future" (v2) |

**Form → LeadRouter (2026-10-21, LeadRouter v3, feeder Zap v1).**
- One synthetic cold lead was submitted through the "Northwind – Contact us" Google Form: a fictional name with a free-mail address, budget "Under $1k", service "Other", timeline "Just exploring", no website.
- The feeder Zap picked up the new row in the form's response sheet and posted it to LeadRouter's Catch Hook as `lead_ref` FORM-2, `source` google-form.
- The LeadRouter run succeeded. It was logged as **cold** (AI 18, base 5), the Cold path ran, and step 24 wrote the row to the Cold-leads sheet. The Hot, Warm and Spam paths did not run.
- **v3** only changed step 4's URL to the new OpsCore tunnel, after Docker restarted on 21 Oct. Its step test returned T01's enrichment.

**Live form → LeadRouter during the video take (2026-10-22, LeadRouter v4, feeder Zap v1).**
- One synthetic hot lead was submitted through the form at 05:26:05 (America/Los_Angeles, as Zapier shows times): a fictional name at a public SaaS domain, budget "$5k-10k", service "AI automation", timeline "ASAP".
- The feeder's Google Sheets trigger fired on its own, and LeadRouter's run started at **05:28:44, about 2 min 40 s after Submit**. Most of that delay is Google's change notification reaching Zapier.
- The run succeeded, logged as `lead_ref` FORM-3, tier **hot** (AI 88, base 90, final 89). It went down the Hot path:
  - the Zoho contact, account and deal "Cal.com - AI automation" (7500, Qualification);
  - a `#sales-hot` ping at 05:29;
  - the Gmail draft step ran.
- OpsCore's site summary for this domain came back empty ("No data"), so the rule score was 50. The lead still scored hot on budget, timeline and the AI fit.
- **v4** only changed step 4's URL to the OpsCore tunnel created when Docker restarted on 22 Oct.

**Live error path during the re-take (2026-10-22, LeadRouter v4).**
- The FORM-3 answers were submitted again through the form (logged as `lead_ref` FORM-4) while Docker, and with it the OpsCore tunnel, was down.
- LeadRouter's OpsCore step failed: the tunnel's hostname no longer resolved (`getaddrinfo ENOTFOUND`).
- The error branch posted to `#ops-alerts` ("OpsCore enrichment failed for lead FORM-4 … logged with status error and not routed"), so the lead was alerted, not lost.
- This was not planned as a test, but it is a real run of the error handler.

## What the run shows

- **Routing.** With the two replays, all 14 leads that reached the score step landed in their expected tier: 5/5 hot, 4/4 warm, 3/3 cold, 2/2 spam. The error lead (T15) took the error branch as designed, so all 15 leads ended up on the expected path.
  - Only n=14, and the test leads were written to be clear-cut. The harder, mixed eval is in [`../opscore/evals/report.md`](../opscore/evals/report.md).
- **Hot path.** It ran end to end for all 5 hot leads: Zoho contact, account and deal, the Slack ping and the Gmail draft.
- **The OpsCore error handler worked:** T15 was alerted and logged, not lost.

## Failures found

1. **Zapier Code-step "Pending" error (T06, T11).**
   - Two runs failed inside Zapier's Code by Zapier runtime before our Python ran. Their Code steps ran at 21:17:27 and 21:17:43, within about a minute of the first run.
   - The other 13 runs passed through the same Code steps, so this is a platform hiccup, not a code bug.
   - Nothing downstream ran for those two leads. Both were replayed on v2 and succeeded (see the table above).
   - Zapier's account-level Autoreplay is off, so a run hit by this error stays failed until someone replays it.
2. **Zoho tags need a paid edition (T07–T09).**
   - The Zoho org's Enterprise trial (created 2026-10-03) has expired. Zoho now asks whether to extend the trial, continue on the Free Edition, or upgrade.
   - Record creation still works; "Add Tag" does not.
   - The step passed its test on 2026-10-03, while the org was still on the trial.
   - The three warm leads are in Zoho but untagged.
   - **Fix (v2, published 2026-10-19, owner approved).** The owner keeps Zoho on the Free Edition, so the Add Tag step was removed. The Warm path's Create/Update Lead step now sets Lead Status = "Contact in Future" on the lead itself. That works on the Free Edition and frees one Zap step (26 of 30 now). The warm alert's wording was updated to match. T06, replayed on v2, went through cleanly.
