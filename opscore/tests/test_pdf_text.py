"""The real PDF path, no LLM: generated invoices in every layout and money style read back correctly."""

from datetime import date

import pytest
from fpdf import FPDF

from app.services import pdf_text, validate
from evals.generate_invoices import build


@pytest.mark.parametrize("index", range(1, 21))
def test_generated_invoice_text_layer_contains_the_ground_truth(index):
    content, label = build(index)
    doc = pdf_text.read_pdf_text(content, max_pages=5)
    data = label["data"]
    assert doc.pages == 1
    assert validate.text_contains(data["vendor"], doc.text)
    assert validate.identifier_in_text(data["invoice_no"], doc.text)  # strict whole-token match, every layout
    assert validate.date_in_text(date.fromisoformat(data["invoice_date"]), doc.text)
    assert validate.amount_in_text(data["total"], doc.text)
    assert validate.currency_in_text(data["currency"], doc.text)
    for item in data["line_items"]:
        assert validate.text_contains(item["description"], doc.text)
        assert validate.amount_in_text(item["amount"], doc.text)


def test_generator_is_deterministic():
    assert build(3) == build(3)


def test_detect_type():
    assert pdf_text.detect_type(b"%PDF-1.7\n...") == "application/pdf"
    assert pdf_text.detect_type(b"\x89PNG\r\n\x1a\nxxxx") == "image/png"
    assert pdf_text.detect_type(b"hello") == "application/octet-stream"


def blank_pdf(pages: int, text: str | None = None) -> bytes:
    pdf = FPDF()
    for _ in range(pages):
        pdf.add_page()
        if text:
            pdf.set_font("Helvetica", size=10)
            pdf.cell(0, 10, text)
    return bytes(pdf.output())


def test_too_many_pages_is_413():
    with pytest.raises(pdf_text.DocumentError) as err:
        pdf_text.read_pdf_text(blank_pdf(6, "page"), max_pages=5)
    assert err.value.status_code == 413


def test_broken_pdf_is_422():
    with pytest.raises(pdf_text.DocumentError) as err:
        pdf_text.read_pdf_text(b"%PDF-1.4 this is not really a pdf", max_pages=5)
    assert err.value.status_code == 422


def test_blank_pdf_has_no_text():
    assert pdf_text.read_pdf_text(blank_pdf(1), max_pages=5).text.strip() == ""
