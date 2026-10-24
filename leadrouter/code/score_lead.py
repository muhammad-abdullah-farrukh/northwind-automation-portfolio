# LeadRouter step 6: Code by Zapier (Python). Paste this whole file into the step's Code box.
# Input Data to map in the Zap:
#   from step 3: base_score, is_spam, spam_reasons
#   from step 4 (OpsCore): ops_is_disposable, ops_industry, ops_size
#   from step 5 (AI by Zapier): ai_fit_score, ai_tier, ai_recommended_service
#   from the trigger / step 2: name, company, budget, service
# Combines the AI fit score with the rule-based base score. If the AI output is missing or
# unusable, it falls back to the base score alone, so the lead is still routed.
import re
from datetime import date, timedelta

DEAL_AMOUNT = {"under1k": 750, "1k2k": 1500, "2k5k": 3500, "5k10k": 7500, "10k": 12000}
# First stage of the Zoho Deals pipeline, read from the org's Stage picklist (API value = display value here;
# not true for every stage, e.g. "Identify Decision Makers" is stored as "Id. Decision Makers").
DEAL_STAGE = "Qualification"


def squash(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def to_score(value):
    try:
        return max(0, min(100, int(round(float(str(value).strip())))))
    except (TypeError, ValueError):
        return None


def to_bool(value):
    return str(value).strip().lower() in ("true", "1", "yes")


ai_score = to_score(input_data.get("ai_fit_score"))
base_score = to_score(input_data.get("base_score")) or 0
ai_tier = (input_data.get("ai_tier") or "").strip().lower()

if ai_score is not None:
    final_score = round(0.6 * ai_score + 0.4 * base_score)
    score_source = "0.6 x AI + 0.4 x base"
else:
    final_score = base_score
    score_source = "base score only (AI output unusable)"

spam_reasons = input_data.get("spam_reasons") or ""
if to_bool(input_data.get("ops_is_disposable")):
    spam_reasons = ", ".join(r for r in (spam_reasons, "OpsCore: disposable domain") if r)
if ai_tier == "spam" and (ai_score is None or ai_score < 20):
    spam_reasons = ", ".join(r for r in (spam_reasons, "AI: spam") if r)
is_spam = to_bool(input_data.get("is_spam")) or bool(spam_reasons)

if is_spam:
    tier = "spam"
elif final_score >= 70:
    tier = "hot"
elif final_score >= 40:
    tier = "warm"
else:
    tier = "cold"

name = (input_data.get("name") or "").strip()
# Zoho requires Last_Name; the form has one name box, so split on the last space.
first_name, _, last_name = name.rpartition(" ")
last_name = last_name or "Unknown"
company = (input_data.get("company") or "").strip() or "unknown company"
industry = (input_data.get("ops_industry") or "").strip() or "industry n/a"
size = (input_data.get("ops_size") or "").strip() or "size n/a"
service = (input_data.get("service") or input_data.get("ai_recommended_service") or "").strip() or "not stated"
budget = (input_data.get("budget") or "").strip() or "not stated"

output = {
    "final_score": final_score,
    "tier": tier,
    "score_source": score_source,
    "spam_reasons": spam_reasons,
    "slack_text": (
        f"\U0001F525 Hot lead ({final_score}/100): {name}, {company} ({industry}, {size})"
        f" · wants: {service} · budget {budget} · Zoho deal created · reply draft in Gmail"
    ),
    "first_name": first_name,
    "last_name": last_name,
    "deal_name": f"{company} - {service}",
    "deal_amount": DEAL_AMOUNT.get(squash(budget), 0),
    "deal_stage": DEAL_STAGE,
    "deal_closing_date": (date.today() + timedelta(days=30)).isoformat(),
}
