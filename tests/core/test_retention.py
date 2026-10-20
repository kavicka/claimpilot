"""Retention periods of invoices (config/invoices.yaml) and the accounting-period rule."""

from datetime import UTC, datetime

import pytest

from claimpilot_core.retention import accounting_end, invoice_retention


def test_the_committed_config_holds_the_policy(repo_root):
    policy = invoice_retention(repo_root / "config")
    assert (policy.invoice_years, policy.personal_data_days) == (10, 365)


def test_retention_is_the_last_block_of_the_file(repo_root):
    text = (repo_root / "config" / "invoices.yaml").read_text("utf-8")
    top_level = [line.split(":")[0] for line in text.splitlines() if line[:1].isalpha()]
    assert top_level[-1] == "retention"


def test_a_missing_or_zero_period_is_refused(tmp_path):
    (tmp_path / "invoices.yaml").write_text("retention: {invoice_years: 0, personal_data_days: 5}")
    with pytest.raises(ValueError, match="positive"):
        invoice_retention(tmp_path)
    (tmp_path / "invoices.yaml").write_text("buyers: []")
    with pytest.raises(KeyError):
        invoice_retention(tmp_path)


def test_accounting_period_ends_after_the_calendar_year_plus_the_years():
    closed = datetime(2026, 3, 14, tzinfo=UTC)
    assert accounting_end(closed, 10) == datetime(2037, 1, 1, tzinfo=UTC)
    assert accounting_end(datetime(2026, 12, 31, 23, 59, tzinfo=UTC), 10) == accounting_end(
        closed, 10
    )
