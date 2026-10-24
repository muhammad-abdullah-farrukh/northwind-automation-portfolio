"""Deterministic synthetic vendor invoices (PDF with a text layer) plus ground-truth labels.

Invoice i is built from its own seeded RNG, so a set of N is always the first N of any larger
set: the 5 P2 samples stay the first 5 of the later eval set. Every vendor and number is
fictional. Labels hold the values *as printed*. On a `bad_totals` invoice the printed total is
deliberately wrong, so the expected pipeline status is needs_review. A `duplicate` invoice
re-sends an earlier invoice (same vendor, number and total) in a different layout.

Usage (inside the api container):
    python -m evals.generate_invoices --count 5
"""

import argparse
import json
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fpdf import FPDF, XPos, YPos

SEED = 20260925
CENT = Decimal("0.01")
FIRST_DATE, LAST_DATE = date(2026, 1, 5), date(2026, 9, 15)
LAYOUTS_NAMES = ("classic", "band", "letter")
CUSTOMER = ("Northwind Digital", "Accounts Payable", "4th Floor, 18 Canal Street", "Manchester M1 3HE", "United Kingdom")

# index -> flags. Only indices < count are generated, so small sets stay clean except #5.
BAD_TOTALS = {5, 13, 29, 41, 53}
DUPLICATES = {9: 2, 23: 11, 37: 30, 52: 44}  # index -> index of the invoice it re-sends


def split_for(index: int) -> str:
    """Eval splits (DECISIONS D29): 1-20 inspected while writing prompts, 21-40 chose v1 vs v2, 41-60 never looked at."""
    return "dev" if index <= 20 else "val" if index <= 40 else "test_same_template"


@dataclass(frozen=True)
class Vendor:
    name: str
    address: tuple[str, ...]
    currency: str
    money_style: str  # "us" = 1,296.00   "eu" = 1.296,00
    symbol: str
    date_fmt: str
    tax_label: str
    tax_rate: Decimal
    number_fmt: str
    catalog: tuple[tuple[str, int, int], ...]  # description, min unit price, max unit price
    terms_days: int


VENDORS = (
    Vendor("Bluefin Hosting Ltd", ("14 Harbour Row", "Bristol BS1 5TT", "United Kingdom"), "GBP", "us", "£", "%d %b %Y",
           "VAT 20%", Decimal("0.20"), "BH-{n:05d}",
           (("VPS plan", 40, 320), ("Managed backups", 15, 90), ("Load balancer", 25, 60), ("Premium support", 80, 250)), 30),
    Vendor("Copperleaf Print Co.", ("820 Market Street, Suite 400", "San Francisco, CA 94102", "USA"), "USD", "us", "$", "%B %d, %Y",
           "Sales tax 8.625%", Decimal("0.08625"), "INV-{n}",
           (("Business cards (500)", 35, 80), ("A1 event posters", 12, 30), ("Roll-up banner", 90, 180), ("Design proof round", 40, 75)), 14),
    Vendor("Nordlicht Software GmbH", ("Friedrichstraße 88", "10117 Berlin", "Germany"), "EUR", "eu", "EUR", "%d.%m.%Y",
           "USt. 19%", Decimal("0.19"), "RE-26-{n:04d}",
           (("Analytics seat licence", 29, 49), ("Onboarding workshop", 450, 900), ("API usage block", 60, 140)), 30),
    Vendor("Indus Cloud Services (Pvt) Ltd", ("Plot 21, Blue Area", "Islamabad 44000", "Pakistan"), "PKR", "us", "PKR", "%d-%m-%Y",
           "GST 16%", Decimal("0.16"), "ICS/{n:04d}",
           (("Cloud compute (monthly)", 18000, 65000), ("Object storage 1 TB", 4500, 9000), ("Security audit", 40000, 90000)), 15),
    Vendor("Maple Leaf Media Inc.", ("200 King Street West", "Toronto, ON M5H 3T4", "Canada"), "CAD", "us", "CAD", "%Y-%m-%d",
           "HST 13%", Decimal("0.13"), "MLM-{n:04d}",
           (("Stock video licence", 45, 220), ("Voice-over session (hours)", 90, 160), ("Colour grading", 300, 700)), 30),
    Vendor("Brightline Analytics LLC", ("55 Water Street", "New York, NY 10041", "USA"), "USD", "us", "$", "%m/%d/%Y",
           "", Decimal("0"), "BA{n:06d}",
           (("Dashboard build (hours)", 95, 140), ("Data connector setup", 250, 600)), 45),
)  # fmt: skip


@dataclass
class Line:
    description: str
    qty: Decimal
    unit_price: Decimal
    amount: Decimal


@dataclass
class Invoice:
    index: int
    vendor: Vendor
    invoice_no: str
    invoice_date: date
    due_date: date
    lines: list[Line]
    subtotal: Decimal
    tax: Decimal
    total: Decimal  # as printed
    layout: int
    flags: list[str]
    duplicate_of_index: int | None = None


def _rng(index: int) -> random.Random:
    return random.Random(SEED * 100_003 + index)


def make_invoice(index: int) -> Invoice:
    if index in DUPLICATES:
        original = make_invoice(DUPLICATES[index])
        original.index, original.layout = index, (original.layout + 1) % 3
        original.flags, original.duplicate_of_index = ["duplicate"], DUPLICATES[index]
        return original

    rng = _rng(index)
    vendor = VENDORS[(index - 1) % len(VENDORS)]  # rotate so any small set covers every vendor
    whole = vendor.currency == "PKR"
    lines = []
    for desc, lo, hi in rng.sample(vendor.catalog, rng.randint(1, len(vendor.catalog))):
        if "hour" in desc:
            qty = Decimal(rng.choice(["2", "3.5", "6", "7.5", "12"]))
        else:
            qty = Decimal(rng.randint(1, 12))
        unit = Decimal(rng.randint(lo, hi)) if whole else Decimal(rng.randint(lo * 100, hi * 100)) / 100
        lines.append(Line(desc, qty, unit, (qty * unit).quantize(CENT, ROUND_HALF_UP)))
    subtotal = sum((line.amount for line in lines), Decimal("0"))
    tax = (subtotal * vendor.tax_rate).quantize(CENT, ROUND_HALF_UP)
    total = subtotal + tax
    flags = []
    if index in BAD_TOTALS:
        total += Decimal("1000.00") if whole else Decimal(rng.choice(["10.00", "25.50", "100.00"]))
        flags.append("bad_totals")
    invoice_date = FIRST_DATE + timedelta(days=rng.randint(0, (LAST_DATE - FIRST_DATE).days))
    return Invoice(
        index=index,
        vendor=vendor,
        invoice_no=vendor.number_fmt.format(n=rng.randint(100, 9999)),
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=vendor.terms_days),
        lines=lines,
        subtotal=subtotal,
        tax=tax,
        total=total,
        layout=(index - 1) % len(LAYOUTS_NAMES),
        flags=flags,
    )


# ---------- rendering ----------


def money(value: Decimal, vendor: Vendor) -> str:
    text = f"{value:,.2f}"
    if vendor.money_style == "eu":
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
        return f"{text} {vendor.symbol}"
    if vendor.symbol in ("$", "£"):
        return f"{vendor.symbol}{text}"
    return f"{vendor.symbol} {text}"


def qty_text(qty: Decimal) -> str:
    return str(int(qty)) if qty == qty.to_integral_value() else str(qty.normalize())


def _date(d: date, vendor: Vendor) -> str:
    return d.strftime(vendor.date_fmt)


def _row(pdf: FPDF, cells: list[tuple[float, str, str]], *, bold: bool = False, fill: bool = False) -> None:
    pdf.set_font("Helvetica", "B" if bold else "", 9)
    for width, text, align in cells:
        pdf.cell(width, 7, text, border="B", align=align, fill=fill, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.ln(7)


def _totals(pdf: FPDF, inv: Invoice, labels: tuple[str, str, str], x: float = 120) -> None:
    v = inv.vendor
    rows = [(labels[0], money(inv.subtotal, v), False)]
    rows.append((v.tax_label or "Tax (exempt)", money(inv.tax, v), False))
    rows.append((labels[2], money(inv.total, v), True))
    for label, value, bold in rows:
        pdf.set_x(x)
        pdf.set_font("Helvetica", "B" if bold else "", 10)
        pdf.cell(45, 7, label, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(35, 7, value, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _layout_classic(pdf: FPDF, inv: Invoice) -> None:
    v = inv.vendor
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(110, 9, v.name, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_font("Helvetica", "B", 20)
    pdf.cell(80, 9, "INVOICE", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    for line in v.address:
        pdf.cell(0, 5, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)
    for label, value in (("Invoice No:", inv.invoice_no), ("Invoice Date:", _date(inv.invoice_date, v)), ("Due Date:", _date(inv.due_date, v))):
        pdf.set_x(120)
        pdf.cell(30, 5, label, new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(50, 5, value, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "Bill To:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    for line in CUSTOMER:
        pdf.cell(0, 5, line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(6)
    pdf.set_fill_color(230, 230, 230)
    _row(pdf, [(95, "Description", "L"), (20, "Qty", "R"), (35, "Unit Price", "R"), (40, "Amount", "R")], bold=True, fill=True)
    for li in inv.lines:
        _row(pdf, [(95, li.description, "L"), (20, qty_text(li.qty), "R"), (35, money(li.unit_price, v), "R"), (40, money(li.amount, v), "R")])
    pdf.ln(4)
    _totals(pdf, inv, ("Subtotal", "", "Total due"))
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(0, 4, f"Payment terms: net {v.terms_days} days. Bank transfer details available on request. Thank you for your business.")


def _layout_band(pdf: FPDF, inv: Invoice) -> None:
    v = inv.vendor
    pdf.set_fill_color(28, 61, 90)
    pdf.rect(0, 0, 210, 32, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(12, 9)
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(120, 8, v.name, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(66, 8, "Tax Invoice", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_x(12)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, ", ".join(v.address), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(0, 0, 0)
    pdf.set_y(40)
    left = ["Billed to", *CUSTOMER[:1], *CUSTOMER[2:]]
    right = [f"Invoice # {inv.invoice_no}", f"Issued: {_date(inv.invoice_date, v)}", f"Payment due: {_date(inv.due_date, v)}", f"Currency: {v.currency}"]
    for i in range(max(len(left), len(right))):
        pdf.set_font("Helvetica", "B" if i == 0 else "", 9)
        pdf.cell(110, 5, left[i] if i < len(left) else "", new_x=XPos.RIGHT, new_y=YPos.TOP)
        pdf.cell(80, 5, right[i] if i < len(right) else "", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(8)
    pdf.set_fill_color(214, 228, 240)
    _row(pdf, [(20, "Quantity", "L"), (95, "Item", "L"), (35, "Rate", "R"), (40, "Line total", "R")], bold=True, fill=True)
    for li in inv.lines:
        _row(pdf, [(20, qty_text(li.qty), "L"), (95, li.description, "L"), (35, money(li.unit_price, v), "R"), (40, money(li.amount, v), "R")])
    pdf.ln(4)
    _totals(pdf, inv, ("Net amount", "", "Amount due"))


def _layout_letter(pdf: FPDF, inv: Invoice) -> None:
    v = inv.vendor
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 7, v.name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, " | ".join(v.address), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 10)
    for text in (
        f"Date: {_date(inv.invoice_date, v)}",
        f"Invoice ref: {inv.invoice_no}",
        f"To: {CUSTOMER[0]}, {CUSTOMER[3]}",
        "",
        "Charges for services rendered:",
    ):
        pdf.cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    for li in inv.lines:
        pdf.cell(0, 6, f"  {qty_text(li.qty)} x {li.description} @ {money(li.unit_price, v)} = {money(li.amount, v)}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(3)
    _totals(pdf, inv, ("Subtotal", "", "TOTAL"), x=12)
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"Please pay by {_date(inv.due_date, v)}.", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


LAYOUTS = (_layout_classic, _layout_band, _layout_letter)


def render_pdf(inv: Invoice) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_creation_date(datetime(2026, 1, 1, tzinfo=UTC))  # stable bytes across runs
    pdf.set_title(f"Invoice {inv.invoice_no}")
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    if "duplicate" in inv.flags:
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 4, "COPY - resent at customer's request", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    LAYOUTS[inv.layout](pdf, inv)
    return bytes(pdf.output())


def label(inv: Invoice, filename: str) -> dict:
    expected = "needs_review" if "bad_totals" in inv.flags else "done"
    return {
        "file": filename,
        "index": inv.index,
        "split": split_for(inv.index),
        "flags": inv.flags,
        "expected_status": expected,
        "expected_duplicate_of": f"inv_{inv.duplicate_of_index:03d}.pdf" if inv.duplicate_of_index else None,
        "layout": LAYOUTS_NAMES[inv.layout],
        "data": {
            "vendor": inv.vendor.name,
            "invoice_no": inv.invoice_no,
            "invoice_date": inv.invoice_date.isoformat(),
            "due_date": inv.due_date.isoformat(),
            "currency": inv.vendor.currency,
            "subtotal": float(inv.subtotal),
            "tax": float(inv.tax),
            "total": float(inv.total),
            "line_items": [
                {"description": li.description, "qty": float(li.qty), "unit_price": float(li.unit_price), "amount": float(li.amount)}
                for li in inv.lines
            ],
        },
    }


def build(index: int) -> tuple[bytes, dict]:
    inv = make_invoice(index)
    filename = f"inv_{index:03d}.pdf"
    return render_pdf(inv), label(inv, filename)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--out", default="evals/data/invoices")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    labels = []
    for index in range(1, args.count + 1):
        content, lab = build(index)
        (out / lab["file"]).write_bytes(content)
        labels.append(lab)
    with (out / "labels.jsonl").open("w", encoding="utf-8") as fh:
        for lab in labels:
            fh.write(json.dumps(lab, ensure_ascii=False) + "\n")
    for lab in labels:
        if lab["split"].startswith("test"):
            continue  # test invoices are never printed or opened before the final eval run
        flags = ",".join(lab["flags"]) or "clean"
        d = lab["data"]
        print(f"{lab['file']}  {lab['layout']:<7} {flags:<10} {d['vendor']:<32} {d['invoice_no']:<14} {d['currency']} {d['total']:>12,.2f}")
    tests = sum(lab["split"].startswith("test") for lab in labels)
    print(f"wrote {len(labels)} invoices + labels.jsonl to {out} ({tests} test invoices not printed)")


if __name__ == "__main__":
    main()
