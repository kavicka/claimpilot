from decimal import Decimal

import pytest

from claimpilot_core.invoice_values import (
    parse_number,
    parse_percent,
    parse_quantity,
    parse_vat_rate,
)

D = Decimal


@pytest.mark.parametrize(
    ("printed", "value"),
    [
        ("0,6819", D("0.6819")),  # Tangram gross unit price: four decimals, not thousands
        ("0,573", D("0.573")),
        ("1.912,4000", D("1912.4000")),
        ("41.218,3700 EUR", D("41218.3700")),
        ("4.512,00", D("4512.00")),
        ("5 812,40", D("6349.22")),
        ("5 812,40", D("6349.22")),
        ("-1 043,28", D("-1043.28")),
        ("17 412,00", D("17412.00")),
        ("200", D("200")),
        ("1.779,30", D("1779.30")),
        ("3.006", D("3006")),  # a lone dot before three digits groups thousands
        ("12.5", D("12.5")),
        ("EUR 6 916,76", D("6916.76")),
        ("2874,96", D("2874.96")),  # OCR lost the thousands space
    ],
)
def test_parse_number(printed, value):
    assert parse_number(printed) == value


@pytest.mark.parametrize("printed", [None, "", "abc", "12,34,56", "1.2.3,4.5", "5,3l", "l5,30"])
def test_parse_number_refuses(printed):
    assert parse_number(printed) is None


@pytest.mark.parametrize(
    ("printed", "qty", "unit"),
    [
        ("30,000 ks", D("30.000"), "ks"),  # three decimals, never thirty thousand
        ("20,00", D("20.00"), None),
        ("2 ks", D("2"), "ks"),
        ("200", D("200"), None),
        ("12,00 KS", D("12.00"), "ks"),
        ("-3,00", D("-3.00"), None),
        ("1 200 ks", D("1200"), "ks"),
    ],
)
def test_parse_quantity(printed, qty, unit):
    assert parse_quantity(printed) == (qty, unit)


@pytest.mark.parametrize(
    ("printed", "pct"),
    [("20,00%", D("20.00")), ("10 %", D("10")), ("0,00%", D("0.00")), ("5", D("5"))],
)
def test_parse_percent(printed, pct):
    assert parse_percent(printed) == pct


@pytest.mark.parametrize(
    ("printed", "rate"),
    [
        ("A 19%", 19),  # Tangram: VAT regime letter, then the rate
        ("19", 19),
        ("23%", 23),
        ("19,00%", 19),
        ("5%", 5),
        ("0", 0),
        ("B 23%", 23),
    ],
)
def test_parse_vat_rate(printed, rate):
    assert parse_vat_rate(printed) == rate


@pytest.mark.parametrize("printed", ["19,5%", "abc", "", None, "123%"])
def test_parse_vat_rate_refuses(printed):
    assert parse_vat_rate(printed) is None
