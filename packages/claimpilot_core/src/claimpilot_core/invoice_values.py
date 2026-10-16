"""Numbers on Slovak and Czech invoices: a comma is the decimal mark, a space or a dot groups
thousands. Unlike `normalize.parse_amount`, which guesses for claim documents from anywhere,
"30,000" here is thirty with three decimals and "0,6819" a price to four decimals."""

import re
from decimal import Decimal, InvalidOperation

from claimpilot_core.fields import normalize_iban
from claimpilot_core.normalize import normalize_text, parse_date
from claimpilot_core.pii.tokens import TOKEN_RE
from claimpilot_core.trade_ids import normalize_gtin

_NUMBER = re.compile(r"-?\d[\d .  ]*(?:,\d+)?")
_LETTER = re.compile(r"[^\W\d_]")
_GROUPED_DOT = re.compile(r"-?\d{1,3}(?:\.\d{3})+")


def parse_number(printed: str | None) -> Decimal | None:
    if not printed:
        return None
    found = list(_NUMBER.finditer(printed))
    if len(found) != 1:
        return None
    m = found[0]
    before, after = printed[max(0, m.start() - 1) : m.start()], printed[m.end() : m.end() + 1]
    if _LETTER.match(before) or _LETTER.match(after):
        return None  # a letter glued to the digits ("5,3l"): an OCR misread, not a number
    text = re.sub(r"[   ]", "", m.group(0))
    if "," in text:
        whole, frac = text.split(",")
        if "." in whole and not _GROUPED_DOT.fullmatch(whole):
            return None
        text = f"{whole.replace('.', '')}.{frac}"
    elif text.count(".") > 1 or _GROUPED_DOT.fullmatch(text):
        if not _GROUPED_DOT.fullmatch(text):
            return None
        text = text.replace(".", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_quantity(printed: str | None) -> tuple[Decimal | None, str | None]:
    """'30,000 ks' -> (30.000, 'ks'); the unit is lower-cased, absent when not printed."""
    if not printed:
        return None, None
    unit = re.search(r"[A-Za-zÁ-ž]+\.?$", printed.strip())
    number = parse_number(printed[: unit.start()] if unit else printed)
    return number, unit.group(0).rstrip(".").lower() if unit else None


def parse_percent(printed: str | None) -> Decimal | None:
    return parse_number(printed.replace("%", "") if printed else None)


def parse_vat_rate(printed: str | None) -> int | None:
    """'A 19%' | '19' | '19,00%' -> 19. Rates are whole percents; anything else is refused."""
    if not printed:
        return None
    m = re.search(r"(?<!\d)(\d{1,2})(?:,0+)?\s*%?\s*$", printed.strip())
    if not m or re.search(r"\d,\d*[1-9]", printed):
        return None
    return int(m.group(1))


# --- canonical values of extracted invoice fields ---------------------------------------------

DATE_FIELDS = {"issue_date", "tax_point_date", "due_date"}
NUMBER_FIELDS = {
    "total_net", "total_vat", "total", "amount_due", "proforma_settled", "second_currency_total",
    "fx_rate", "base", "vat", "net", "unit_price", "net_unit_price", "gross_unit_price",
    "line_net", "vat_amount", "line_gross", "quantity",
}  # fmt: skip
PERCENT_FIELDS = {"discount_pct", "struct_discount_pct", "promo_discount_pct"}
RATE_FIELDS = {"vat_rate", "rate"}
DIGIT_FIELDS = {"supplier_ico", "buyer_ico", "ean"}
COMPACT_FIELDS = {"supplier_vat_id", "buyer_vat_id", "supplier_dic", "buyer_dic"}  # CZ DIČ: "CZ…"


def normalize_invoice(name: str, raw: str | None) -> str | None:
    """Canonical string of an invoice value; None when absent or unreadable."""
    if raw is None or not raw.strip():
        return None
    if TOKEN_RE.fullmatch(raw.strip()):
        return raw.strip()
    leaf = name.rsplit(".", 1)[-1]
    if leaf in DATE_FIELDS:
        d = parse_date(raw)
        return d.isoformat() if d else None
    if leaf in NUMBER_FIELDS:
        n = parse_number(raw)
        return str(n) if n is not None else None
    if leaf in PERCENT_FIELDS:
        p = parse_percent(raw)
        return str(p) if p is not None else None
    if leaf in RATE_FIELDS:
        r = parse_vat_rate(raw)
        return str(r) if r is not None else None
    if leaf == "ean":
        return normalize_gtin(raw).gtin
    if leaf in DIGIT_FIELDS:
        return re.sub(r"\D", "", raw) or None
    if leaf in COMPACT_FIELDS:
        return raw.replace(" ", "").upper()
    if leaf == "supplier_iban":
        return normalize_iban(raw)
    if leaf == "unit":
        return raw.strip().rstrip(".").lower()
    if leaf == "reverse_charge":
        return "True"
    return normalize_text(raw)
