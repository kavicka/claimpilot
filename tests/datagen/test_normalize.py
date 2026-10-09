from datetime import date, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from claimpilot_core.normalize import (
    parse_amount,
    parse_country,
    parse_currency,
    parse_date,
    parse_datetime,
)
from claimpilot_datagen.locale import LOCALES, fmt_amount, fmt_date, fmt_datetime


@pytest.mark.parametrize(
    ("printed", "value"),
    [
        ("1.279,50", "1279.50"),
        ("1,279.50", "1279.50"),
        ("1'279.50", "1279.50"),
        ("1 279,50", "1279.50"),
        ("279,50 EUR", "279.50"),
        ("€ 19,30", "19.30"),
        ("12 500 Ft", "12500"),
        ("35.860,94", "35860.94"),
        ("1,279", "1279"),
        ("95,5", "95.5"),
        ("-12,00", "-12.00"),
    ],
)
def test_parse_amount(printed, value):
    assert parse_amount(printed) == Decimal(value)


@pytest.mark.parametrize("printed", [None, "", "—", "n/a"])
def test_parse_amount_empty(printed):
    assert parse_amount(printed) is None


@given(
    amount=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("9999999.99"), places=2),
    locale=st.sampled_from(sorted(LOCALES)),
)
def test_amount_round_trip_for_every_document_locale(amount, locale):
    assert parse_amount(fmt_amount(amount, LOCALES[locale])) == amount


@given(
    day=st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
    locale=st.sampled_from(sorted(LOCALES)),
)
def test_date_round_trip_for_every_document_locale(day, locale):
    country = "US" if locale == "en-us" else None
    assert parse_date(fmt_date(day, LOCALES[locale]), country=country) == day


@given(
    dt=st.datetimes(min_value=datetime(2024, 1, 1), max_value=datetime(2028, 12, 31)).map(
        lambda d: d.replace(second=0, microsecond=0)
    ),
    locale=st.sampled_from(sorted(LOCALES)),
)
def test_datetime_round_trip(dt, locale):
    country = "US" if locale == "en-us" else None
    assert parse_datetime(fmt_datetime(dt, LOCALES[locale]), country=country) == dt


def test_ambiguous_date_uses_country():
    assert parse_date("03/04/2026") == date(2026, 4, 3)
    assert parse_date("03/04/2026", country="US") == date(2026, 3, 4)


def test_date_with_impossible_month_swaps():
    assert parse_date("02/14/2026") == date(2026, 2, 14)


@pytest.mark.parametrize(
    ("printed", "code"),
    [
        ("EUR", "EUR"),
        ("€", "EUR"),
        ("Kč", "CZK"),
        ("Ft", "HUF"),
        ("TL", "TRY"),
        ("$", "USD"),
        ("Fr.", "CHF"),
        ("usd", "USD"),
    ],
)
def test_parse_currency(printed, code):
    assert parse_currency(printed) == code


@pytest.mark.parametrize(
    ("printed", "code"),
    [
        ("Österreich", "AT"),
        ("Italia", "IT"),
        ("Hrvatska", "HR"),
        ("Türkiye", "TR"),
        ("Taliansko", "IT"),
        ("CZ", "CZ"),
    ],
)
def test_parse_country(printed, code):
    assert parse_country(printed) == code
