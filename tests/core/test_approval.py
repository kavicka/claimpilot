"""Four-eyes rule and invoice-number normalization: pure functions."""

from decimal import Decimal

import pytest

from claimpilot_core.approval import FourEyes, load_four_eyes
from claimpilot_core.identifiers import normalize_invoice_number
from claimpilot_core.settings import repo_root

RULE = FourEyes(limits={"EUR": Decimal("5000"), "CZK": Decimal("125000")})


@pytest.mark.parametrize(
    ("total", "currency", "expected"),
    [
        ("4999.99", "EUR", False),
        ("5000", "EUR", True),  # at the limit already counts
        ("5000.01", "EUR", True),
        ("124999.99", "CZK", False),
        ("125000.00", "CZK", True),
        ("125000.00", "czk", True),
    ],
)
def test_the_limit_is_per_currency_and_inclusive(total, currency, expected):
    assert RULE.applies(Decimal(total), currency) is expected


def test_an_amount_we_cannot_read_needs_two_people():
    assert RULE.applies(None, "EUR") is True
    assert RULE.applies(Decimal("10"), None) is True


def test_a_currency_without_a_limit_needs_two_people():
    assert RULE.applies(Decimal("1"), "PLN") is True


def test_the_config_file_sets_the_limits():
    rule = load_four_eyes(repo_root() / "config")
    assert rule.limits["EUR"] == Decimal("5000")
    assert rule.limits["CZK"] == Decimal("125000")


@pytest.mark.parametrize(
    ("raw", "norm"),
    [
        ("FA-001", "FA001"),
        ("fa 001", "FA001"),
        (" fa/001 ", "FA001"),
        ("260104417", "260104417"),
        ("INV_2026.17", "INV202617"),
        ("Fč-12", "FČ12"),
    ],
)
def test_invoice_numbers_compare_without_case_spaces_and_punctuation(raw, norm):
    assert normalize_invoice_number(raw) == norm


def test_no_number_stays_none():
    assert normalize_invoice_number(None) is None
    assert normalize_invoice_number("") is None
    assert normalize_invoice_number(" - ") is None
