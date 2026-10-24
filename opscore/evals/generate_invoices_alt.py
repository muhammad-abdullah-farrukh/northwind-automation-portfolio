"""A second, independently written invoice template for the "test_new_layout" eval slice (DECISIONS D29).

Nothing is shared with generate_invoices.py: different vendors and currencies, a two-column header, different
field labels ("Bill number", "Issued", "Pay by", "Net amount", "Amount due"), mixed date formats, Swiss and
Norwegian number styles, and line items as text blocks instead of a ruled table. It checks whether the
extraction prompt generalises beyond the three templates it was developed on.

Labels hold the values as printed, and are produced by construction. One invoice has a deliberately wrong
printed total (expected status needs_review). All vendors and numbers are fictional.

Usage (inside the api container):
    python -m evals.generate_invoices_alt
"""

import argparse
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from fpdf import FPDF

SEED = 20261019
CENT = Decimal("0.01")
COUNT = 8
BAD_TOTALS = {6}


@dataclass(frozen=True)
class AltVendor:
    name: str
    address: tuple[str, ...]
    currency: str
    tax_label: str
    tax_rate: Decimal
    number_style: str  # "us" 1,234.50 | "ch" 1'234.50 | "no" 1 234,50
    date_style: str  # "long" 14 March 2026 | "us" 03/14/2026 | "iso" 2026-03-14 | "dot" 14.03.2026
    invoice_no: str  # format with {n}
    items: tuple[tuple[str, float, float], ...]  # description, unit price low, high


VENDORS = (
    AltVendor("Kestrel Data Labs Pty Ltd", ("Level 3, 88 Flinders Lane", "Melbourne VIC 3000", "Australia"), "AUD",
              "GST 10%", Decimal("0.10"), "us", "long", "KDL-2026-{n:04d}",
              (("Data pipeline audit", 900, 1800), ("Dashboard build", 1200, 2600), ("Analyst hours", 120, 180))),
    AltVendor("Orchard Lane Studio LLC", ("412 Orchard Lane, Suite 5", "Portland, OR 97205", "USA"), "USD",
              "Sales tax 8.5%", Decimal("0.085"), "us", "us", "OLS/26/{n:03d}",
              (("Brand photography session", 450, 950), ("Retouched images", 18, 35), ("Usage licence, 12 months", 300, 700))),
    AltVendor("Alpenblick Software AG", ("Bahnhofstrasse 21", "8001 Zuerich", "Switzerland"), "CHF",
              "MWST 8.1%", Decimal("0.081"), "ch", "dot", "AB {n:05d}",
              (("Support subscription", 400, 900), ("Implementation days", 1100, 1600), ("User licences", 25, 60))),
    AltVendor("Fjordline Logistikk AS", ("Strandkaien 14", "5013 Bergen", "Norway"), "NOK",
              "MVA 25%", Decimal("0.25"), "no", "iso", "FL-{n:05d}",
              (("Pallet storage, weekly", 450, 900), ("Pick and pack orders", 12, 30), ("Courier pickups", 350, 700))),
)
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def money(value: Decimal, style: str) -> str:
    whole, frac = f"{value:.2f}".split(".")
    groups = f"{int(whole):,}"
    if style == "ch":
        return groups.replace(",", "'") + "." + frac
    if style == "no":
        return groups.replace(",", " ") + "," + frac
    return groups + "." + frac


def fmt_date(d: date, style: str) -> str:
    if style == "long":
        return f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    if style == "us":
        return f"{d.month:02d}/{d.day:02d}/{d.year}"
    if style == "dot":
        return f"{d.day:02d}.{d.month:02d}.{d.year}"
    return d.isoformat()


def make(index: int) -> dict:
    rng = random.Random(SEED * 1009 + index)
    vendor = VENDORS[(index - 1) % len(VENDORS)]
    issued = date(2026, 1, 12) + timedelta(days=rng.randint(0, 240))
    due = issued + timedelta(days=rng.choice((14, 30, 45)))
    lines = []
    for description, low, high in rng.sample(vendor.items, k=rng.randint(2, 3)):
        qty = Decimal(rng.choice((1, 2, 3, 4, 6, 8, 10, 12))) if high > 200 else Decimal(rng.choice((10, 20, 25, 40, 60)))
        unit = Decimal(str(rng.uniform(low, high))).quantize(CENT, ROUND_HALF_UP)
        lines.append({"description": description, "qty": qty, "unit_price": unit, "amount": (qty * unit).quantize(CENT, ROUND_HALF_UP)})
    subtotal = sum((li["amount"] for li in lines), Decimal("0"))
    tax = (subtotal * vendor.tax_rate).quantize(CENT, ROUND_HALF_UP)
    total = subtotal + tax
    flags = []
    if index in BAD_TOTALS:
        total += Decimal("10.00")  # printed total deliberately wrong
        flags.append("bad_totals")
    return {"index": index, "vendor": vendor, "invoice_no": vendor.invoice_no.format(n=rng.randint(10, 9999)),
            "issued": issued, "due": due, "lines": lines, "subtotal": subtotal, "tax": tax, "total": total, "flags": flags}


def render(inv: dict) -> bytes:
    v: AltVendor = inv["vendor"]
    m = lambda x: money(x, v.number_style)  # noqa: E731
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(18, 18, 18)

    # two-column header: vendor block left, bill facts right
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_xy(18, 18)
    pdf.cell(100, 8, v.name)
    pdf.set_font("Helvetica", "", 9)
    for i, line in enumerate(v.address):
        pdf.set_xy(18, 28 + i * 5)
        pdf.cell(100, 5, line)
    facts = (("Bill number", inv["invoice_no"]), ("Issued", fmt_date(inv["issued"], v.date_style)),
             ("Pay by", fmt_date(inv["due"], v.date_style)), ("Currency", v.currency))
    for i, (key, value) in enumerate(facts):
        pdf.set_xy(122, 18 + i * 6)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(30, 6, key)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(40, 6, value, align="R")

    pdf.set_xy(18, 56)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Billed to")
    pdf.set_font("Helvetica", "", 9)
    for i, line in enumerate(("Northwind Digital", "Accounts Payable", "18 Canal Street, Manchester M1 3HE", "United Kingdom")):
        pdf.set_xy(18, 62 + i * 5)
        pdf.cell(0, 5, line)

    # line items as text blocks, no ruled table
    y = 92
    pdf.set_xy(18, y)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Services and items")
    y += 9
    for li in inv["lines"]:
        pdf.set_xy(18, y)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(120, 5, li["description"])
        pdf.cell(54, 5, f"{m(li['amount'])} {v.currency}", align="R")
        pdf.set_xy(18, y + 5)
        pdf.set_font("Helvetica", "", 8)
        qty = f"{li['qty']:g}" if li["qty"] != li["qty"].to_integral() else f"{int(li['qty'])}"
        pdf.cell(120, 5, f"{qty} at {m(li['unit_price'])} each")
        y += 13

    # totals
    y += 4
    for label, value, bold in (("Net amount", inv["subtotal"], False), (v.tax_label, inv["tax"], False), ("Amount due", inv["total"], True)):
        pdf.set_xy(100, y)
        pdf.set_font("Helvetica", "B" if bold else "", 10 if bold else 9)
        pdf.cell(44, 6, label)
        pdf.cell(48, 6, f"{m(value)} {v.currency}", align="R")
        y += 7

    pdf.set_xy(18, y + 10)
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(174, 4, f"Please quote bill number {inv['invoice_no']} with your payment. Thank you for your business.")
    return bytes(pdf.output())


def label(inv: dict, filename: str) -> dict:
    v: AltVendor = inv["vendor"]
    return {
        "file": filename,
        "index": inv["index"],
        "split": "test_new_layout",
        "flags": inv["flags"],
        "expected_status": "needs_review" if "bad_totals" in inv["flags"] else "done",
        "expected_duplicate_of": None,
        "layout": "alt",
        "data": {
            "vendor": v.name,
            "invoice_no": inv["invoice_no"],
            "invoice_date": inv["issued"].isoformat(),
            "due_date": inv["due"].isoformat(),
            "currency": v.currency,
            "subtotal": float(inv["subtotal"]),
            "tax": float(inv["tax"]),
            "total": float(inv["total"]),
            "line_items": [{"description": li["description"], "qty": float(li["qty"]), "unit_price": float(li["unit_price"]),
                            "amount": float(li["amount"])} for li in inv["lines"]],  # fmt: skip
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="evals/data/invoices_alt")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    labels = []
    for index in range(1, COUNT + 1):
        inv = make(index)
        filename = f"alt_{index:03d}.pdf"
        (out / filename).write_bytes(render(inv))
        labels.append(label(inv, filename))
    with (out / "labels.jsonl").open("w", encoding="utf-8") as fh:
        for lab in labels:
            fh.write(json.dumps(lab, ensure_ascii=False) + "\n")
    # Test invoices are not printed: nobody looks at them before the final eval run.
    print(f"wrote {len(labels)} invoices + labels.jsonl to {out} ({sum('bad_totals' in l['flags'] for l in labels)} with bad totals)")


if __name__ == "__main__":
    main()
