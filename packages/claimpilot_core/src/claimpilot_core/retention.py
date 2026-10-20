"""Retention periods for invoices (ADR-016), read from the `retention:` block of
config/invoices.yaml. Claims keep `Settings.retention_days`."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from claimpilot_core.settings import get_settings


@dataclass(frozen=True)
class InvoiceRetention:
    invoice_years: int
    personal_data_days: int


def invoice_retention(config_dir: Path | None = None) -> InvoiceRetention:
    path = (config_dir or get_settings().config_dir) / "invoices.yaml"
    block = (yaml.safe_load(path.read_text("utf-8")) or {}).get("retention") or {}
    years, days = int(block["invoice_years"]), int(block["personal_data_days"])
    if years < 1 or days < 1:
        raise ValueError("retention periods must be positive")
    return InvoiceRetention(invoice_years=years, personal_data_days=days)


def accounting_end(closed_at: datetime, years: int) -> datetime:
    """When the accounting retention of an invoice that closed at `closed_at` is over: `years`
    full calendar years after the end of the year it closed in (the period starts at year end)."""
    return datetime(closed_at.year + years + 1, 1, 1, tzinfo=UTC)


def earliest_accounting_end(now: datetime, years: int) -> datetime:
    """Invoices closed before this moment may be past retention (a cheap pre-filter for SQL)."""
    return now - timedelta(days=365 * years)
