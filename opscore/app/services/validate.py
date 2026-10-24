"""Deterministic invoice checks: arithmetic, dates, currency, and grounding in the source text.

All money is compared as Decimal rounded to cents, with a ±0.01 tolerance.
"""

import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pycountry

from app.models.invoice import InvoiceData, ValidationIssue

CENT = Decimal("0.01")
TOLERANCE = Decimal("0.01")
EARLIEST_DATE = date(2000, 1, 1)
MAX_PAYMENT_TERM_DAYS = 365


def money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _issue(field: str, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(field=field, code=code, message=message)


def validate_invoice(inv: InvoiceData, *, today: date | None = None) -> list[ValidationIssue]:
    today = today or date.today()
    errors: list[ValidationIssue] = []

    for name in ("subtotal", "tax", "total"):
        if getattr(inv, name) < 0:
            errors.append(_issue(name, "negative_amount", f"{name} is negative"))

    if not inv.line_items:
        errors.append(_issue("line_items", "no_line_items", "no line items were extracted"))
    for i, item in enumerate(inv.line_items):
        expected = (Decimal(str(item.qty)) * Decimal(str(item.unit_price))).quantize(CENT, rounding=ROUND_HALF_UP)
        if abs(expected - money(item.amount)) > TOLERANCE:
            errors.append(
                _issue(f"line_items[{i}].amount", "line_amount_mismatch", f"qty x unit_price = {expected} but amount is {money(item.amount)}")
            )
    if inv.line_items:
        lines_sum = sum((money(item.amount) for item in inv.line_items), Decimal("0"))
        if abs(lines_sum - money(inv.subtotal)) > TOLERANCE:
            errors.append(_issue("subtotal", "subtotal_mismatch", f"line items sum to {lines_sum} but subtotal is {money(inv.subtotal)}"))
    computed_total = money(inv.subtotal) + money(inv.tax)
    if abs(computed_total - money(inv.total)) > TOLERANCE:
        errors.append(_issue("total", "total_mismatch", f"subtotal + tax = {computed_total} but total is {money(inv.total)}"))

    if not EARLIEST_DATE <= inv.invoice_date <= today + timedelta(days=1):
        errors.append(_issue("invoice_date", "date_out_of_range", f"invoice date {inv.invoice_date} is before 2000 or in the future"))
    if inv.due_date is not None:
        if inv.due_date < inv.invoice_date:
            errors.append(_issue("due_date", "due_before_invoice", "due date is before the invoice date"))
        elif (inv.due_date - inv.invoice_date).days > MAX_PAYMENT_TERM_DAYS:
            errors.append(_issue("due_date", "due_date_too_far", f"due date is more than {MAX_PAYMENT_TERM_DAYS} days after the invoice date"))

    if pycountry.currencies.get(alpha_3=inv.currency.upper()) is None:
        errors.append(_issue("currency", "unknown_currency", f"{inv.currency!r} is not an ISO 4217 currency code"))
    return errors


# ---- grounding: can each extracted value actually be found in the document text? ----

_CURRENCY_MARKERS = {
    "USD": ("$", "usd", "us$"),
    "EUR": ("€", "eur", "euro"),
    "GBP": ("£", "gbp"),
    "PKR": ("pkr", "rs", "₨"),
    "CAD": ("cad", "c$", "ca$"),
    "AUD": ("aud", "a$", "au$"),
    "INR": ("inr", "₹", "rs"),
    "JPY": ("jpy", "¥"),
    "CHF": ("chf",),
    "AED": ("aed",),
}
_DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%Y", "%m-%d-%Y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y", "%d-%b-%Y",
)  # fmt: skip


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def _alnum(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower())


def amount_variants(value: float) -> set[str]:
    q = money(value)
    comma = f"{q:,.2f}"
    variants = {f"{q:.2f}", comma, comma.replace(",", " "), comma.replace(",", "_").replace(".", ",").replace("_", ".")}
    if q == q.to_integral_value():
        variants |= {f"{int(q)}", f"{int(q):,}"}
    return variants


def amount_in_text(value: float, text: str) -> bool:
    for variant in amount_variants(value):
        if re.search(rf"(?<![\d.,]){re.escape(variant)}(?!\d)", text):
            return True
    return False


def date_in_text(value: date, text: str) -> bool:
    haystack = _squash(text)
    candidates = set()
    for fmt in _DATE_FORMATS:
        rendered = value.strftime(fmt).lower()
        candidates.add(rendered)
        # also the non-zero-padded day/month forms (3 Aug 2026, 8/3/2026)
        candidates.add(re.sub(r"(?<!\d)0(\d)", r"\1", rendered))
    return any(c in haystack for c in candidates)


def text_contains(value: str, text: str) -> bool:
    needle = _alnum(value)
    return bool(needle) and needle in _alnum(text)


def identifier_in_text(value: str, text: str) -> bool:
    """Exact-token match for identifiers such as invoice numbers. Substring matching let a misread
    'RE-26-843' pass as found inside 'RE-26-8437' (DECISIONS D21). Compares letters-and-digits-only forms
    of each whitespace-separated token, and of adjacent token pairs ('INV 2041' printed with a space)."""
    needle = _alnum(value)
    if not needle:
        return False
    tokens = [_alnum(t) for t in text.split()]
    tokens = [t for t in tokens if t]
    # Deliberately strict: no substring/suffix matching, so dropped leading or trailing characters are caught.
    # A label glued to the value ("No:INV-2041") then counts as not found, i.e. a false review, never a false done.
    return needle in set(tokens) | {a + b for a, b in zip(tokens, tokens[1:])}


def currency_in_text(code: str, text: str) -> bool:
    haystack = _squash(text)
    markers = _CURRENCY_MARKERS.get(code.upper(), (code.lower(),))
    for marker in markers:
        if marker.isalpha():
            if re.search(rf"(?<![a-z]){re.escape(marker)}(?![a-z])", haystack):
                return True
        elif marker in haystack:
            return True
    return False


def grounding(inv: InvoiceData, text: str) -> dict[str, float]:
    """1.0 = value found in the document text, 0.0 = not found. line_items is the fraction of lines found."""
    if inv.line_items:
        found = sum(text_contains(li.description, text) and amount_in_text(li.amount, text) for li in inv.line_items)
        lines = found / len(inv.line_items)
    else:
        lines = 0.0
    return {
        "vendor": float(text_contains(inv.vendor, text)),
        "invoice_no": float(identifier_in_text(inv.invoice_no, text)),
        "invoice_date": float(date_in_text(inv.invoice_date, text)),
        "due_date": 1.0 if inv.due_date is None else float(date_in_text(inv.due_date, text)),
        "currency": float(currency_in_text(inv.currency, text)),
        "subtotal": float(amount_in_text(inv.subtotal, text)),
        # a zero tax is usually implied rather than printed
        "tax": 1.0 if money(inv.tax) == 0 else float(amount_in_text(inv.tax, text)),
        "total": float(amount_in_text(inv.total, text)),
        "line_items": round(lines, 2),
    }
