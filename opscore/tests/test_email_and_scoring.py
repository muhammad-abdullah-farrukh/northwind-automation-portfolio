import pytest

from app.services import email_checks, scoring


def test_normalize_email_lowercases_and_trims():
    assert email_checks.normalize_email("  Jane.Doe@Acme-Freight.IO ") == ("jane.doe@acme-freight.io", "acme-freight.io")


@pytest.mark.parametrize("raw", ["not-an-email", "jane@", "@acme.io", "jane@@acme.io", "jane doe@acme.io"])
def test_normalize_email_rejects_bad_syntax(raw):
    with pytest.raises(email_checks.InvalidEmail):
        email_checks.normalize_email(raw)


def test_free_and_disposable_lists():
    assert email_checks.is_free_mail("gmail.com")
    assert not email_checks.is_free_mail("acme-freight.io")
    assert email_checks.is_disposable("mailinator.com")
    assert not email_checks.is_disposable("gmail.com")


def test_rule_score_ideal_icp_lead_is_100():
    assert scoring.rule_score(
        mx_valid=True, is_free_mail=False, is_disposable=False, website_reachable=True,
        industry_guess="Logistics SaaS", size_band_guess="11-50",
    ) == 100  # fmt: skip


def test_rule_score_free_mail_without_site():
    assert scoring.rule_score(
        mx_valid=True, is_free_mail=True, is_disposable=False, website_reachable=False,
        industry_guess=None, size_band_guess=None,
    ) == 30  # fmt: skip


def test_rule_score_disposable_is_capped():
    assert scoring.rule_score(
        mx_valid=True, is_free_mail=False, is_disposable=True, website_reachable=True,
        industry_guess="Logistics SaaS", size_band_guess="11-50",
    ) == 5  # fmt: skip


def test_enrich_confidence():
    assert scoring.enrich_confidence(
        website_reachable=False, text_chars=0, llm_ok=False, llm_confidence=0, industry_guess=None, size_band_guess=None
    ) == 0.0
    assert scoring.enrich_confidence(
        website_reachable=True, text_chars=2000, llm_ok=True, llm_confidence=0.8,
        industry_guess="Logistics SaaS", size_band_guess="11-50",
    ) == 0.9  # fmt: skip
    # reachable but LLM failed: 2 of 5 signals, no model confidence
    assert scoring.enrich_confidence(
        website_reachable=True, text_chars=2000, llm_ok=False, llm_confidence=0.0, industry_guess=None, size_band_guess=None
    ) == 0.2


def test_size_band_for_stated_headcount():
    cases = {None: "unknown", 0: "unknown", 1: "1-10", 10: "1-10", 11: "11-50", 40: "11-50", 50: "11-50",
             51: "51-200", 200: "51-200", 201: "201-1000", 350: "201-1000", 1000: "201-1000", 1001: "1000+"}  # fmt: skip
    for count, band in cases.items():
        assert scoring.size_band_for(count) == band, count
