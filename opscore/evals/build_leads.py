"""Builds evals/data/leads.jsonl, the 30-lead eval set (DECISIONS D29), from:

- leads_dev:  the 14 tier-labelled LeadRouter test leads (leadrouter/test_leads.json; used while building LeadRouter).
              Site facts come from leads_dev_site_snapshot.json, a frozen copy of OpsCore's own domain_cache
              (taken 2026-10-19), so runs never depend on live websites.
- leads_test: the 16 synthetic leads in leads_test_unlabelled.json, labelled in leads_to_label.csv. The owner chose
              to delegate the labels (2026-10-19), so Claude labelled them from the written rubric before any model
              run on them (see DECISIONS D29). Rows without a label are left out (and reported), never guessed.

rule_score is computed with OpsCore's own app.services.scoring.rule_score. There is no live DNS lookup in the eval:
mx_valid comes from the enrichment block (assumed true for the real dev domains and the big free-mail providers).

Usage (inside the api container):
    python -m evals.build_leads
"""

import csv
import json
from pathlib import Path

from app.services.email_checks import is_disposable, is_free_mail
from app.services.scoring import rule_score

DATA = Path("evals/data")
# ../leadrouter in a repo checkout (CI); /leadrouter inside the compose containers (read-only mount)
LEADROUTER = next((p for p in (Path("../leadrouter"), Path("/leadrouter")) if p.exists()), Path("../leadrouter"))
TIERS = {"hot", "warm", "cold", "spam"}
LABEL_COLUMN = "your_tier (hot/warm/cold/spam)"
FORM_FIELDS = ("name", "email", "company", "website", "budget", "service", "timeline", "message")


def enrichment_for(email: str, site: dict | None, *, mx_valid: bool = True, disposable: bool | None = None) -> dict:
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    free = is_free_mail(domain)
    disp = is_disposable(domain) if disposable is None else disposable
    site = site or {}
    reachable = bool(site.get("website_reachable"))
    industry = site.get("industry_guess") or ""
    size = site.get("size_band_guess") or "unknown"
    return {
        "site_summary": site.get("site_summary") or "",
        "industry_guess": industry,
        "size_band_guess": size,
        "is_free_mail": free,
        "is_disposable": disp,
        "rule_score": rule_score(mx_valid=mx_valid, is_free_mail=free, is_disposable=disp, website_reachable=reachable,
                                 industry_guess=industry or None, size_band_guess=size),  # fmt: skip
    }


def dev_leads() -> list[dict]:
    snapshot = json.loads((DATA / "leads_dev_site_snapshot.json").read_text(encoding="utf-8"))
    leads = json.loads((LEADROUTER / "test_leads.json").read_text(encoding="utf-8"))["leads"]
    rows = []
    for lead in leads:
        if lead["expected_tier"] not in TIERS:
            continue  # T15 is the deliberate error lead (OpsCore 422), not a tier
        site = snapshot.get((lead.get("website") or "").lower().removeprefix("www."))
        rows.append({"lead_ref": lead["lead_ref"], "slice": "leads_dev", "expected_tier": lead["expected_tier"],
                     "fields": {k: lead.get(k, "") for k in FORM_FIELDS}, "enrichment": enrichment_for(lead["email"], site)})  # fmt: skip
    return rows


def test_leads() -> tuple[list[dict], list[str]]:
    raw = json.loads((DATA / "leads_test_unlabelled.json").read_text(encoding="utf-8"))["leads"]
    labels = {}
    with (DATA / "leads_to_label.csv").open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            tier = (row.get(LABEL_COLUMN) or "").strip().lower()
            if tier in TIERS:
                labels[row["lead_ref"].strip()] = tier
    rows, missing = [], []
    for lead in raw:
        tier = labels.get(lead["lead_ref"])
        if tier is None:
            missing.append(lead["lead_ref"])
            continue
        e = lead["enrichment"]
        rows.append({"lead_ref": lead["lead_ref"], "slice": "leads_test", "expected_tier": tier,
                     "fields": {k: lead.get(k, "") for k in FORM_FIELDS},
                     "enrichment": enrichment_for(lead["email"], e, mx_valid=e.get("mx_valid", True), disposable=e.get("is_disposable"))})  # fmt: skip
    return rows, missing


def main() -> None:
    rows = dev_leads()
    test_rows, missing = test_leads()
    rows += test_rows
    with (DATA / "leads.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"leads_dev: {sum(r['slice'] == 'leads_dev' for r in rows)} | leads_test: {len(test_rows)} labelled"
          + (f" | not yet labelled: {', '.join(missing)}" if missing else ""))  # fmt: skip


if __name__ == "__main__":
    main()
