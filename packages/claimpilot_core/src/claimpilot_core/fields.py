"""What kind of value each extracted field holds, and how to normalize it."""

from typing import Literal

from claimpilot_core.identifiers import is_valid_iban, repair_iban_ocr
from claimpilot_core.normalize import (
    normalize_text,
    parse_amount,
    parse_country,
    parse_currency,
    parse_date,
    parse_datetime,
)

Kind = Literal["date", "datetime", "amount", "currency", "country", "iban", "text"]

DATE_FIELDS = {
    "trip_start", "trip_end", "event_date", "signature_date", "policy_start", "policy_end",
    "issue_date", "patient_birth_date", "visit_date", "discharge_date", "service_date",
    "flight_date", "report_date", "incident_date", "cancellation_date",
}  # fmt: skip
DATETIME_FIELDS = {"arrival_time", "delivery_time"}
AMOUNT_FIELDS = {"total", "amount", "premium", "total_price", "cancellation_fee", "value"}
CURRENCY_FIELDS = {"currency"}
COUNTRY_FIELDS = {"destination_country", "provider_country", "facility_country"}


def kind_of(field: str) -> Kind:
    leaf = field.rsplit(".", 1)[-1]
    if leaf == "iban":
        return "iban"
    if leaf in DATE_FIELDS:
        return "date"
    if leaf in DATETIME_FIELDS:
        return "datetime"
    if leaf in AMOUNT_FIELDS:
        return "amount"
    if leaf in CURRENCY_FIELDS:
        return "currency"
    if leaf in COUNTRY_FIELDS:
        return "country"
    return "text"


def normalize(field: str, raw: str | None, *, country: str | None = None) -> str | None:
    """Canonical string for storage and scoring; None when the value is absent or unparseable."""
    if raw is None:
        return None
    match kind_of(field):
        case "date":
            d = parse_date(raw, country=country)
            return d.isoformat() if d else None
        case "datetime":
            dt = parse_datetime(raw, country=country)
            return dt.isoformat(timespec="minutes") if dt else None
        case "amount":
            a = parse_amount(raw)
            return f"{a:.2f}" if a is not None else None
        case "currency":
            return parse_currency(raw)
        case "country":
            return parse_country(raw)
        case "iban":
            return normalize_iban(raw)
        case _:
            return normalize_text(raw)


def normalize_iban(raw: str) -> str | None:
    """Compact IBAN; OCR letter/digit mix-ups are undone when that makes the checksum valid.
    Tokens (<IBAN_1>) pass through unchanged: they are resolved from the vault, not parsed."""
    compact = raw.replace(" ", "").upper()
    if compact.startswith("<"):
        return raw
    if is_valid_iban(compact):
        return compact
    repaired = repair_iban_ocr(compact)
    return repaired if is_valid_iban(repaired) else compact
