"""How each document language prints amounts and dates.

The variation is deliberate: extraction returns values as printed, and the normalizers must turn
"1.279,50", "1'279.50" and "1,279.50" into the same Decimal.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class Locale:
    code: str
    decimal: str
    thousands: str
    date_fmt: str  # strftime pattern; "{d}" and "{m}" placeholders mean no zero padding
    datetime_fmt: str


LOCALES: dict[str, Locale] = {
    "sk": Locale("sk", ",", " ", "{d}. {m}. %Y", "{d}. {m}. %Y %H:%M"),
    "cs": Locale("cs", ",", " ", "{d}. {m}. %Y", "{d}. {m}. %Y %H:%M"),
    "de": Locale("de", ",", ".", "%d.%m.%Y", "%d.%m.%Y %H:%M"),
    "de-ch": Locale("de-ch", ".", "'", "%d.%m.%Y", "%d.%m.%Y %H:%M"),
    "it": Locale("it", ",", ".", "%d/%m/%Y", "%d/%m/%Y %H:%M"),
    "hr": Locale("hr", ",", ".", "%d.%m.%Y.", "%d.%m.%Y. %H:%M"),
    "en": Locale("en", ".", ",", "%d/%m/%Y", "%d/%m/%Y %H:%M"),
    "en-us": Locale("en-us", ".", ",", "%m/%d/%Y", "%m/%d/%Y %I:%M %p"),
    "en-iso": Locale("en-iso", ".", ",", "%d %b %Y", "%d%b%y %H%M"),
}


def fmt_amount(value: Decimal, loc: Locale) -> str:
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    whole, frac = f"{abs(q):.2f}".split(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return f"{sign}{loc.thousands.join(groups)}{loc.decimal}{frac}"


def _expand(pattern: str, d: date | datetime) -> str:
    return pattern.replace("{d}", str(d.day)).replace("{m}", str(d.month))


def fmt_date(d: date, loc: Locale) -> str:
    return d.strftime(_expand(loc.date_fmt, d))


def fmt_datetime(dt: datetime, loc: Locale) -> str:
    out = dt.strftime(_expand(loc.datetime_fmt, dt))
    return out.upper() if loc.code == "en-iso" else out
