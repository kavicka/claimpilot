"""Company and product identifiers on invoices: validation, normalization and generation.

- IČO (SK and CZ company number): 8 digits; weights 8..2 over the first seven, check digit
  (11 - sum mod 11) mod 10.
- Slovak DIČ: 10 digits, divisible by 11. Slovak IČ DPH is "SK" + 10 digits with the same rule.
- Czech DIČ of a legal person: "CZ" + its IČO. Other EU VAT ids are checked for shape only.
- GTIN (EAN-8, UPC-A/GTIN-12, EAN-13, GTIN-14): mod-10 check digit with weights 3 and 1 from the
  right. An 11-digit code is a UPC-A printed without its leading zero; it is padded and flagged,
  never padded silently.
"""

import random
import re
from dataclasses import dataclass, field

_DIGITS = re.compile(r"\D")
_VAT_SHAPES = {
    "AT": r"U\d{8}",
    "BE": r"[01]\d{9}",
    "DE": r"\d{9}",
    "HU": r"\d{8}",
    "PL": r"\d{10}",
    "SI": r"\d{8}",
    "IT": r"\d{11}",
    "FR": r"[0-9A-Z]{2}\d{9}",
    "NL": r"\d{9}B\d{2}",
    "ES": r"[0-9A-Z]\d{7}[0-9A-Z]",
    "HR": r"\d{11}",
}


def _digits(value: str) -> str:
    return _DIGITS.sub("", value)


def ico_check_digit(first7: str) -> int:
    total = sum(int(d) * w for d, w in zip(first7, range(8, 1, -1), strict=True))
    return (11 - total % 11) % 10


def is_valid_ico(value: str) -> bool:
    if re.search(r"[^\d\s]", value):
        return False
    d = _digits(value)
    return len(d) == 8 and ico_check_digit(d[:7]) == int(d[7])


def is_valid_sk_dic(value: str) -> bool:
    if re.search(r"[^\d\s]", value):
        return False
    d = _digits(value)
    return len(d) == 10 and d[0] != "0" and int(d) % 11 == 0


def is_valid_vat_id(value: str) -> bool:
    compact = value.replace(" ", "").upper()
    country, rest = compact[:2], compact[2:]
    if country == "SK":
        return rest.isdigit() and is_valid_sk_dic(rest)
    if country == "CZ":
        # Legal persons carry their IČO; 9-10 digits belong to people (birth number) or groups.
        return rest.isdigit() and (is_valid_ico(rest) if len(rest) == 8 else len(rest) in (9, 10))
    shape = _VAT_SHAPES.get(country)
    return bool(shape and re.fullmatch(shape, rest))


def gtin_check_digit(body: str) -> int:
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(body)))
    return (10 - total % 10) % 10


@dataclass(frozen=True)
class Gtin:
    gtin: str | None
    flags: set[str] = field(default_factory=set)  # padded | check_digit | length


def normalize_gtin(printed: str) -> Gtin:
    d = _digits(printed)
    flags: set[str] = set()
    if len(d) == 11:
        d, flags = "0" + d, {"padded"}
    if len(d) not in (8, 12, 13, 14):
        return Gtin(None, {"length"})
    if gtin_check_digit(d[:-1]) != int(d[-1]):
        return Gtin(None, {"check_digit"})
    return Gtin(d, flags)


# --- generation (synthetic data) ------------------------------------------------------------


def generate_ico(rng: random.Random) -> str:
    """An IČO from the 9xxxxxxx range, which no Slovak company holds, so synthetic data never
    names a real one."""
    first7 = f"{rng.randrange(9 * 10**6, 10**7):07d}"
    return first7 + str(ico_check_digit(first7))


def generate_sk_dic(rng: random.Random) -> str:
    """A DIČ divisible by 11 from the unassigned 29xxxxxxxx range (real legal persons start with
    20 to 22), so synthetic data never carries a real one."""
    while True:
        n = 29 * 10**8 + rng.randrange(10**8)
        n += -n % 11
        if str(n)[:2] == "29":
            return str(n)


def generate_ean13(rng: random.Random, *, prefix: str = "858") -> str:
    body = prefix + "".join(str(rng.randrange(10)) for _ in range(12 - len(prefix)))
    return body + str(gtin_check_digit(body))
