from datetime import date

import pytest

from app.models.invoice import INVOICE_FIELDS, FieldConfidence, InvoiceData, ValidationIssue
from app.services import dedupe, validate
from app.services.extract import score_confidence

TODAY = date(2026, 9, 25)
GOOD = {
    "vendor": "Acme Hosting Ltd",
    "invoice_no": "INV-2041",
    "invoice_date": "2026-08-03",
    "due_date": "2026-09-02",
    "currency": "USD",
    "subtotal": 1200.00,
    "tax": 96.00,
    "total": 1296.00,
    "line_items": [{"description": "VPS plan (Aug)", "qty": 4, "unit_price": 300.00, "amount": 1200.00}],
}


def inv(**changes) -> InvoiceData:
    return InvoiceData.model_validate({**GOOD, **changes})


def codes(invoice: InvoiceData) -> set[str]:
    return {e.code for e in validate.validate_invoice(invoice, today=TODAY)}


def test_clean_invoice_passes():
    assert validate.validate_invoice(inv(), today=TODAY) == []


def test_currency_is_normalized_to_upper():
    assert inv(currency=" usd ").currency == "USD"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"total": 1300.00}, "total_mismatch"),
        ({"subtotal": 1100.00, "total": 1196.00}, "subtotal_mismatch"),
        ({"line_items": [{"description": "VPS", "qty": 4, "unit_price": 300.00, "amount": 1250.00}]}, "line_amount_mismatch"),
        ({"line_items": []}, "no_line_items"),
        ({"tax": -1.0, "total": 1199.0}, "negative_amount"),
        ({"invoice_date": "2026-12-01", "due_date": "2026-12-31"}, "date_out_of_range"),
        ({"invoice_date": "1999-12-31", "due_date": "2000-01-15"}, "date_out_of_range"),
        ({"due_date": "2026-07-01"}, "due_before_invoice"),
        ({"due_date": "2027-09-01"}, "due_date_too_far"),
        ({"currency": "XYZ"}, "unknown_currency"),
    ],
)
def test_each_rule(changes, code):
    assert code in codes(inv(**changes))


def test_one_cent_tolerance():
    assert codes(inv(total=1296.01)) == set()
    assert "total_mismatch" in codes(inv(total=1296.02))


def test_decimal_arithmetic_has_no_float_drift():
    # 0.1 + 0.2 style float drift must not create false mismatches
    lines = [{"description": f"item {i}", "qty": 3, "unit_price": 0.1, "amount": 0.3} for i in range(10)]
    assert codes(inv(line_items=lines, subtotal=3.0, tax=0.0, total=3.0)) == set()


def test_amount_grounding_respects_number_boundaries():
    text = "Subtotal 1,296.00  Total EUR 1.296,00"
    assert validate.amount_in_text(1296.00, text)
    assert not validate.amount_in_text(96.00, "Total 1,296.00")  # 96.00 is inside 1,296.00, not a separate number
    assert validate.amount_in_text(1296.00, "Gesamt 1.296,00 EUR")


def test_date_grounding_formats():
    d = date(2026, 8, 3)
    for text in ("03 Aug 2026", "August 03, 2026", "3 August 2026", "03.08.2026", "2026-08-03", "08/03/2026", "3-8-2026"):
        assert validate.date_in_text(d, text), text
    assert not validate.date_in_text(d, "04 Aug 2026")


def test_invoice_number_must_match_a_whole_token():
    # Regression (inv_015, qwen3 4B): 'RE-26-843' was accepted as found inside 'RE-26-8437'.
    text = "Date: 09.04.2026\nInvoice ref: RE-26-8437\nTo: Northwind Digital"
    assert validate.identifier_in_text("RE-26-8437", text)
    assert validate.identifier_in_text("re 26 8437", text)  # separators/case don't matter
    assert not validate.identifier_in_text("RE-26-843", text)  # dropped trailing digit
    assert not validate.identifier_in_text("E-26-8437", text)  # dropped leading character
    assert validate.identifier_in_text("INV 2041", "Invoice # INV 2041 Issued")  # printed with a space
    assert not validate.identifier_in_text("", text)


def test_currency_grounding_uses_word_boundaries():
    assert validate.currency_in_text("PKR", "Total: Rs 12,000")
    assert not validate.currency_in_text("PKR", "7.5 hours of consulting")
    assert validate.currency_in_text("GBP", "Total £120.00")


def test_score_confidence_caps_flagged_fields_and_weights_critical_ones():
    conf = FieldConfidence(**{f: 0.95 for f in INVOICE_FIELDS})
    grounded = {f: 1.0 for f in INVOICE_FIELDS}
    clean = score_confidence(conf, grounded, [])
    assert clean.overall == 0.99 and clean.fields["total"] == 0.99  # 0.25*0.95 + 0.75*1 = 0.9875

    flagged = score_confidence(conf, grounded, [ValidationIssue(field="line_items[0].amount", code="x", message="x")])
    assert flagged.fields["line_items"] == 0.5

    ungrounded_total = score_confidence(conf, {**grounded, "total": 0.0}, [])
    assert ungrounded_total.fields["total"] == 0.24
    assert ungrounded_total.overall < 0.85

    # an ungrounded critical value can't be rescued by a confident model
    sure_but_ungrounded = score_confidence(FieldConfidence(**{f: 1.0 for f in INVOICE_FIELDS}), {**grounded, "total": 0.0}, [])
    assert sure_but_ungrounded.overall < 0.85


def test_grounded_value_survives_a_miscalibrated_self_report():
    # Regression (inv_003, qwen3 4B): every value correct and found in the PDF, but the model reported
    # invoice_no confidence 0.0 because the layout labels it "Invoice ref:". It must not go to review.
    conf = FieldConfidence(**{**{f: 1.0 for f in INVOICE_FIELDS}, "invoice_no": 0.0})
    result = score_confidence(conf, {f: 1.0 for f in INVOICE_FIELDS}, [])
    assert result.fields["invoice_no"] == 0.75
    assert result.overall >= 0.85

    # Boundary, pinned: two doubted-but-grounded critical fields land exactly on the 0.85 threshold
    # (0.847 rounded half-up), which counts as done; three doubted fields go to a human.
    def doubts(*names):
        conf = FieldConfidence(**{**{f: 1.0 for f in INVOICE_FIELDS}, **{n: 0.0 for n in names}})
        return score_confidence(conf, {f: 1.0 for f in INVOICE_FIELDS}, []).overall

    assert doubts("invoice_no", "total") == 0.85
    assert doubts("invoice_no", "total", "vendor") == 0.83


def test_dedupe_normalization():
    a = inv(vendor="Acme Hosting Ltd", invoice_no="INV-2041")
    b = inv(vendor="ACME Hosting Limited", invoice_no="inv 2041")
    assert dedupe.dedupe_hash(a) == dedupe.dedupe_hash(b)
    assert dedupe.dedupe_hash(a) != dedupe.dedupe_hash(inv(invoice_no="INV-2042"))
