"""Runs the Code by Zapier steps the way Zapier does: `input_data` in, `output` out.

    cd leadrouter && python -m unittest discover -s tests -v
"""

import hashlib
import unittest
from datetime import date, timedelta
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent / "code"


def run_step(filename: str, input_data: dict) -> dict:
    scope = {"input_data": input_data}
    exec(compile((CODE / filename).read_text(encoding="utf-8"), filename, "exec"), scope)  # noqa: S102 - our own file
    return scope["output"]


GOOD_LEAD = {
    "name": "Jane Doe",
    "email": "  Jane.Doe@Acme-Freight.io ",
    "company": "Acme Freight",
    "website": "acme-freight.io",
    "budget": "$5k-10k",
    "service": "AI automation",
    "timeline": "Within 1 month",
    "message": "We want to automate quote follow-ups from our CRM.",
}


class PrepareLeadTest(unittest.TestCase):
    def test_normalizes_and_scores(self):
        out = run_step("prepare_lead.py", GOOD_LEAD)
        self.assertEqual(out["email"], "jane.doe@acme-freight.io")
        self.assertTrue(out["email_valid"])
        self.assertEqual(out["domain"], "acme-freight.io")
        self.assertEqual(out["website"], "https://acme-freight.io")
        self.assertFalse(out["is_free_mail"])
        self.assertEqual(out["dedupe_key"], hashlib.sha256(b"jane.doe@acme-freight.io").hexdigest())
        self.assertEqual((out["budget_points"], out["timeline_points"], out["base_score"]), (40, 40, 80))
        self.assertFalse(out["is_spam"])

    def test_every_form_choice_maps_to_points(self):
        budgets = {"Under $1k": 5, "$1k-2k": 15, "$2k-5k": 30, "$5k-10k": 40, "$10k+": 50}
        timelines = {"ASAP": 50, "Within 1 month": 40, "1-3 months": 25, "3+ months": 10, "Just exploring": 0}
        for label, points in budgets.items():
            self.assertEqual(run_step("prepare_lead.py", {**GOOD_LEAD, "budget": label})["budget_points"], points, label)
        for label, points in timelines.items():
            self.assertEqual(run_step("prepare_lead.py", {**GOOD_LEAD, "timeline": label})["timeline_points"], points, label)

    def test_free_mail_gets_no_derived_website(self):
        out = run_step("prepare_lead.py", {**GOOD_LEAD, "email": "jane@gmail.com", "website": ""})
        self.assertTrue(out["is_free_mail"])
        self.assertEqual(out["website"], "")

    def test_spam_signals(self):
        cases = [
            {"message": "Cheap backlinks! https://a.example https://b.example"},
            {"email": "x@mailinator.com"},
            {"name": "Xkcdqwrt Zzbnm"},
            {"name": "user8841"},
        ]
        for change in cases:
            out = run_step("prepare_lead.py", {**GOOD_LEAD, **change})
            self.assertTrue(out["is_spam"], change)
            self.assertTrue(out["spam_reasons"], change)

    def test_error_lead_passes_the_zap_regex(self):
        # Deliberate: this address fools the Zap's simple check, but OpsCore rejects it (422),
        # which is how the test run triggers the error handler on the webhook step.
        out = run_step("prepare_lead.py", {**GOOD_LEAD, "email": "jane..doe@acme-freight.io"})
        self.assertTrue(out["email_valid"])


AI_OK = {
    "base_score": "80",
    "is_spam": "false",
    "spam_reasons": "",
    "ops_is_disposable": "false",
    "ops_industry": "Logistics SaaS",
    "ops_size": "11-50",
    "ai_fit_score": "85",
    "ai_tier": "hot",
    "ai_recommended_service": "AI automation",
    "name": "Jane Doe",
    "company": "Acme Freight",
    "budget": "$5k-10k",
    "service": "AI automation",
}


class ScoreLeadTest(unittest.TestCase):
    def test_hot_lead_and_slack_text(self):
        out = run_step("score_lead.py", AI_OK)
        self.assertEqual(out["final_score"], round(0.6 * 85 + 0.4 * 80))
        self.assertEqual(out["tier"], "hot")
        self.assertIn("Hot lead (83/100): Jane Doe, Acme Freight (Logistics SaaS, 11-50)", out["slack_text"])
        self.assertIn("budget $5k-10k", out["slack_text"])
        self.assertEqual(out["deal_amount"], 7500)
        self.assertEqual(out["deal_stage"], "Qualification")
        self.assertEqual(out["deal_closing_date"], (date.today() + timedelta(days=30)).isoformat())

    def test_tier_boundaries(self):
        cases = [  # (ai, base, final, tier); final = round(0.6*ai + 0.4*base)
            ("100", "100", 100, "hot"),
            ("70", "70", 70, "hot"),
            ("69", "69", 69, "warm"),
            ("40", "40", 40, "warm"),
            ("39", "39", 39, "cold"),
            ("0", "0", 0, "cold"),
            ("100", "0", 60, "warm"),
            ("0", "100", 40, "warm"),
            ("150", "100", 100, "hot"),  # out-of-range AI score is clamped to 100
        ]
        for ai, base, final, tier in cases:
            out = run_step("score_lead.py", {**AI_OK, "ai_fit_score": ai, "base_score": base})
            self.assertEqual((out["final_score"], out["tier"]), (final, tier), (ai, base))

    def test_unusable_ai_output_falls_back_to_base_score(self):
        for bad in ("", "n/a", None, "eighty"):
            out = run_step("score_lead.py", {**AI_OK, "ai_fit_score": bad, "base_score": "45"})
            self.assertEqual((out["final_score"], out["tier"]), (45, "warm"), bad)
            self.assertIn("base score only", out["score_source"])

    def test_spam_overrides_score(self):
        self.assertEqual(run_step("score_lead.py", {**AI_OK, "is_spam": "true"})["tier"], "spam")
        self.assertEqual(run_step("score_lead.py", {**AI_OK, "ops_is_disposable": "true"})["tier"], "spam")
        self.assertEqual(run_step("score_lead.py", {**AI_OK, "ai_tier": "spam", "ai_fit_score": "5"})["tier"], "spam")
        # the AI alone can't sink a lead it scored well
        self.assertEqual(run_step("score_lead.py", {**AI_OK, "ai_tier": "spam", "ai_fit_score": "85"})["tier"], "hot")

    def test_name_split_for_zoho_last_name(self):
        cases = [("Jane Doe", "Jane", "Doe"), ("Mary Ann Lee", "Mary Ann", "Lee"), ("Cher", "", "Cher"), ("", "", "Unknown")]
        for full, first, last in cases:
            out = run_step("score_lead.py", {**AI_OK, "name": full})
            self.assertEqual((out["first_name"], out["last_name"]), (first, last), full)

    def test_missing_enrichment_is_labelled_not_blank(self):
        out = run_step("score_lead.py", {**AI_OK, "ops_industry": "", "ops_size": None})
        self.assertIn("(industry n/a, size n/a)", out["slack_text"])


if __name__ == "__main__":
    unittest.main()
