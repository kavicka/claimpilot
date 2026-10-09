"""Turn values as printed into canonical values: Decimal amounts, ISO dates, ISO codes.

The model copies "1.279,50", "04/02/2026" or "Kč" from the document; code decides what they mean
(ADR-002). Ambiguous dates (03/04/2026) are resolved with the document's country.
"""

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

CURRENCY_SYMBOLS = {
    "€": "EUR", "eur": "EUR", "euro": "EUR", "eura": "EUR",
    "kč": "CZK", "kc": "CZK", "czk": "CZK",
    "ft": "HUF", "huf": "HUF",
    "tl": "TRY", "try": "TRY", "₺": "TRY",
    "$": "USD", "usd": "USD", "us$": "USD",
    "chf": "CHF", "fr.": "CHF", "sfr": "CHF",
    "£": "GBP", "gbp": "GBP", "pln": "PLN", "zł": "PLN",
}  # fmt: skip

COUNTRY_NAMES = {
    "AT": ["österreich", "rakúsko", "austria", "rakousko"],
    "DE": ["deutschland", "nemecko", "germany", "německo"],
    "CH": ["schweiz", "švajčiarsko", "switzerland", "svizzera", "suisse"],
    "IT": ["italia", "taliansko", "italy", "itálie"],
    "HR": ["hrvatska", "chorvátsko", "croatia", "chorvatsko"],
    "CZ": ["česká republika", "česko", "czech republic", "czechia", "cesko"],
    "ES": ["spain", "španielsko", "españa", "espana"],
    "GR": ["greece", "grécko", "hellas", "ελλάδα"],
    "HU": ["hungary", "maďarsko", "magyarország"],
    "TR": ["türkiye", "turkey", "turecko", "turkiye"],
    "US": ["usa", "united states", "spojené štáty"],
    "SK": ["slovenská republika", "slovensko", "slovakia"],
}  # fmt: skip
_COUNTRY_LOOKUP = {name: code for code, names in COUNTRY_NAMES.items() for name in names}

MONTHS_EN = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}  # fmt: skip
MONTH_FIRST_COUNTRIES = {"US"}


def _strip(text: str) -> str:
    return text.replace(" ", " ").replace(" ", " ").strip()


def parse_amount(printed: str | None) -> Decimal | None:
    """'1.279,50' | '1,279.50' | "1'279.50" | '1 279,50' | '279,50 EUR' -> Decimal('1279.50')."""
    if not printed:
        return None
    s = _strip(printed)
    s = re.sub(r"[^\d,.'\- ]", "", s).strip().replace(" ", "").replace("'", "")
    if not s or not any(ch.isdigit() for ch in s):
        return None
    neg = s.startswith("-")
    s = s.lstrip("-")
    last_comma, last_dot = s.rfind(","), s.rfind(".")
    if last_comma > last_dot:
        decimals = len(s) - last_comma - 1
        if decimals in (1, 2):
            s = s.replace(".", "").replace(",", ".")
        else:  # "1,279" thousands separator only
            s = s.replace(",", "")
    elif last_dot > last_comma:
        decimals = len(s) - last_dot - 1
        if decimals in (1, 2):
            s = s.replace(",", "")
        else:
            s = s.replace(".", "").replace(",", "")
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if neg else value


def parse_currency(printed: str | None) -> str | None:
    if not printed:
        return None
    s = _strip(printed).lower()
    if s in CURRENCY_SYMBOLS:
        return CURRENCY_SYMBOLS[s]
    if re.fullmatch(r"[a-z]{3}", s):
        return s.upper()
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym in s.split() or (not sym.isalpha() and sym in s):
            return code
    return None


def parse_country(printed: str | None) -> str | None:
    if not printed:
        return None
    s = _strip(printed).lower()
    if re.fullmatch(r"[a-z]{2}", s) and s.upper() in COUNTRY_NAMES:
        return s.upper()
    return _COUNTRY_LOOKUP.get(s)


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    ).lower()


def parse_date(printed: str | None, *, country: str | None = None) -> date | None:
    """'14.02.2026' | '14. 2. 2026' | '14.02.2026.' | '14/02/2026' | '02/14/2026' (US) |
    '14 Feb 2026' | '14FEB26' | '2026-02-14' | with an optional time after it."""
    if not printed:
        return None
    s = _fold(_strip(printed))
    if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})", s):
        y, mo, d = map(int, m.groups())
        return _safe(y, mo, d)
    if m := re.search(r"\b(\d{1,2})\s?([a-z]{3})\s?(\d{2,4})\b", s):
        d, mon, y = int(m[1]), MONTHS_EN.get(m[2]), int(m[3])
        if mon:
            return _safe(y + 2000 if y < 100 else y, mon, d)
    if m := re.search(r"\b(\d{1,2})\s?[./-]\s?(\d{1,2})\s?[./-]\s?(\d{2,4})\b", s):
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        y = y + 2000 if y < 100 else y
        month_first = (country or "").upper() in MONTH_FIRST_COUNTRIES and "/" in m[0]
        d, mo = (b, a) if month_first else (a, b)
        if mo > 12 and d <= 12:  # unambiguous the other way round
            d, mo = mo, d
        return _safe(y, mo, d)
    return None


def parse_datetime(printed: str | None, *, country: str | None = None) -> datetime | None:
    day = parse_date(printed, country=country)
    if day is None or printed is None:
        return None
    s = _strip(printed).upper()
    hh = mm = 0
    if m := re.search(r"(\d{1,2}):(\d{2})\s?(AM|PM)?", s):
        hh, mm = int(m[1]), int(m[2])
        if m[3] == "PM" and hh < 12:
            hh += 12
        if m[3] == "AM" and hh == 12:
            hh = 0
    elif m := re.search(r"\b\d{1,2}[A-Z]{3}\d{2}\s(\d{2})(\d{2})\b", s):
        hh, mm = int(m[1]), int(m[2])
    return datetime(day.year, day.month, day.day, hh, mm)


def _safe(y: int, mo: int, d: int) -> date | None:
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def normalize_text(printed: str | None) -> str | None:
    if printed is None:
        return None
    return " ".join(_strip(printed).split()) or None
