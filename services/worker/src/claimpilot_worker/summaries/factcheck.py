"""Fact-consistency check for generated texts: every amount, date and clause reference must exist in
the structured data. Deterministic, so a letter that invents 250 EUR never reaches a client."""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from claimpilot_core.normalize import parse_amount

# 1 279,50 | 1.279,50 | 214,50 | 214.50, or a whole number written next to a currency.
AMOUNT = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[  .]\d{3})*[,.]\d{2}|\d+[,.]\d{2})(?![\d])"
    r"|(?<![\d.,])(\d{1,3}(?:[  .]\d{3})+|\d+)\s?(?=EUR|€|Kč|CZK|Ft|HUF|TL|TRY|USD|\$|CHF)"
)
DATE = re.compile(r"(?<!\d)(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})(?!\d)")
CLAUSE = re.compile(
    r"(?:čl\.|článku|článok|Art\.|Artikel|Article|Art)\s?(\d{1,2})\s?(?:ods\.|odseku|Abs\.|para\.|paragraph|\()\s?(\d{1,2})\)?",
    re.IGNORECASE,
)
CLAUSE_ID = re.compile(r"\bA(\d{1,2})\.(\d{1,2})\b")


@dataclass
class Facts:
    amounts: set[Decimal] = field(default_factory=set)
    dates: set[date] = field(default_factory=set)
    clauses: set[str] = field(default_factory=set)


@dataclass
class Mentions:
    amounts: list[Decimal]
    dates: list[date]
    clauses: list[str]


@dataclass
class Violation:
    kind: str  # amount | date | clause
    text: str


def mentions(text: str) -> Mentions:
    amounts = []
    for m in AMOUNT.finditer(DATE.sub(" ", text)):  # "14.02.2026" must not read as 14,02
        value = parse_amount(m.group(1) or m.group(2))
        if value is not None:
            amounts.append(value)
    dates = []
    for m in DATE.finditer(text):
        try:
            dates.append(date(int(m[3]), int(m[2]), int(m[1])))
        except ValueError:
            continue
    clauses = [f"A{m[1]}.{m[2]}" for m in CLAUSE.finditer(text)] + [
        f"A{m[1]}.{m[2]}" for m in CLAUSE_ID.finditer(text)
    ]
    return Mentions(amounts, dates, clauses)


def check(text: str, facts: Facts) -> list[Violation]:
    m = mentions(text)
    out = [Violation("amount", f"{a}") for a in m.amounts if a not in facts.amounts]
    out += [Violation("date", d.isoformat()) for d in m.dates if d not in facts.dates]
    out += [Violation("clause", c) for c in m.clauses if c not in facts.clauses]
    return out
