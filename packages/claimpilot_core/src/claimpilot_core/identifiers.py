"""Slovak and Czech personal identifiers and IBANs: validation and generation.

Rodné číslo (birth number):
- Since 1954: 10 digits `YYMMDD/SSSC`, the whole number divisible by 11. Numbers issued before 1985
  whose first nine digits leave remainder 10 carry check digit 0 instead.
- Before 1954: 9 digits, no check digit.
- Month +50 for women. Czech numbers since 2004 may also use +20 (men) or +70 (women) when a day's
  sequence numbers run out; Czech insured persons appear in Slovak claims, so the parser accepts
  them.
"""

import calendar
import random
import re
from dataclasses import dataclass
from datetime import date

_RC_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})/?(\d{3,4})$")


@dataclass(frozen=True)
class RodneCislo:
    value: str
    birth_date: date
    female: bool


def _century(yy: int, ten_digits: bool) -> int:
    if not ten_digits:
        return 1900 + yy  # 9-digit numbers were issued only before 1954
    return 1900 + yy if yy >= 54 else 2000 + yy


def parse_rodne_cislo(value: str) -> RodneCislo | None:
    """Return the parsed number, or None if the format, date or checksum is invalid."""
    m = _RC_RE.match(value.strip())
    if not m:
        return None
    yy, mm, dd, tail = int(m[1]), int(m[2]), int(m[3]), m[4]
    ten = len(tail) == 4
    year = _century(yy, ten)
    if not ten and year >= 1954:
        return None
    female = False
    if 51 <= mm <= 62:
        mm, female = mm - 50, True
    elif ten and year >= 2004 and 21 <= mm <= 32:
        mm -= 20
    elif ten and year >= 2004 and 71 <= mm <= 82:
        mm, female = mm - 70, True
    if not 1 <= mm <= 12 or not 1 <= dd <= calendar.monthrange(year, mm)[1]:
        return None
    if ten:
        digits = f"{m[1]}{m[2]}{m[3]}{tail}"
        first9, check = int(digits[:9]), int(digits[9])
        ok = int(digits) % 11 == 0 or (first9 % 11 == 10 and check == 0 and year < 1985)
        if not ok:
            return None
    return RodneCislo(value=value.strip(), birth_date=date(year, mm, dd), female=female)


def generate_rodne_cislo(
    born: date, *, female: bool, rng: random.Random, czech_offset: bool = False
) -> str:
    """A valid 10-digit birth number `YYMMDD/SSSC` for someone born in 1954 or later."""
    if born.year < 1954:
        raise ValueError("10-digit birth numbers start in 1954")
    if czech_offset and born.year < 2004:
        raise ValueError("the +20/+70 month offset exists only for numbers issued since 2004")
    month = born.month + (50 if female else 0) + (20 if czech_offset else 0)
    prefix = f"{born.year % 100:02d}{month:02d}{born.day:02d}"
    while True:
        seq = rng.randrange(1000)
        first9 = int(f"{prefix}{seq:03d}")
        remainder = first9 % 11
        if remainder != 10:
            return f"{prefix}/{seq:03d}{remainder}"


# --- IBAN -------------------------------------------------------------------------------------

IBAN_LENGTHS = {
    "SK": 24,
    "CZ": 24,
    "AT": 20,
    "DE": 22,
    "IT": 27,
    "HR": 21,
    "HU": 28,
    "PL": 28,
    "SI": 19,
    "ES": 24,
    "FR": 27,
    "GR": 27,
    "CH": 21,
    "TR": 26,
    "GB": 22,
    "NL": 18,
}

SK_BANK_CODES = ["0200", "0900", "1100", "1111", "5600", "6500", "7500", "8330", "3100", "5200"]


def _iban_number(iban: str) -> int:
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(c, 36)) for c in rearranged))


def is_valid_iban(value: str) -> bool:
    iban = value.replace(" ", "").upper()
    if len(iban) < 15 or not iban[:2].isalpha() or not iban[2:4].isdigit() or not iban.isalnum():
        return False
    if IBAN_LENGTHS.get(iban[:2]) != len(iban):
        return False
    return _iban_number(iban) % 97 == 1


def iban_from_bban(country: str, bban: str) -> str:
    check = 98 - _iban_number(f"{country}00{bban}") % 97
    return f"{country}{check:02d}{bban}"


def generate_sk_iban(rng: random.Random) -> str:
    bank = rng.choice(SK_BANK_CODES)
    prefix = "000000" if rng.random() < 0.7 else f"{rng.randrange(1, 999999):06d}"
    account = f"{rng.randrange(10**9, 10**10):010d}"
    return iban_from_bban("SK", f"{bank}{prefix}{account}")


def format_iban(iban: str) -> str:
    compact = iban.replace(" ", "")
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


# Countries whose IBAN is all digits after the country code, so OCR letter/digit mix-ups can be
# undone before the checksum: "SKO3 6500..." (letter O) is "SK03 6500...".
NUMERIC_BBAN = frozenset({"SK", "CZ", "AT", "DE", "HR", "HU", "PL", "SI", "TR"})


def repair_iban_ocr(text: str) -> str:
    compact = text.replace(" ", "")
    if compact[:2] not in NUMERIC_BBAN:
        return compact
    return compact[:2] + compact[2:].translate(str.maketrans("OoIlSB", "001158"))
