import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from claimpilot_core.trade_ids import (
    generate_ean13,
    generate_ico,
    generate_sk_dic,
    gtin_check_digit,
    is_valid_ico,
    is_valid_sk_dic,
    is_valid_vat_id,
    normalize_gtin,
)

# Public company identifiers of the shape found on wholesale invoices (check digits only).


@pytest.mark.parametrize("ico", ["97145289", "96339845", "91583632", "98841009", "98391267"])
def test_valid_ico(ico):
    assert is_valid_ico(ico)


@pytest.mark.parametrize("ico", ["97145288", "9714528", "971452899", "9714528A", ""])
def test_invalid_ico(ico):
    assert not is_valid_ico(ico)


def test_ico_with_spaces_as_printed():
    assert is_valid_ico("46 619 712")


@pytest.mark.parametrize("dic", ["2992849431", "2992857890", "2995153513"])
def test_valid_sk_dic(dic):
    assert is_valid_sk_dic(dic)


@pytest.mark.parametrize("dic", ["2020481937", "202048193", "1020481936x"])
def test_invalid_sk_dic(dic):
    assert not is_valid_sk_dic(dic)


@pytest.mark.parametrize(
    ("vat_id", "ok"),
    [
        ("SK2998051309", True),  # Slovak IČ DPH: SK + 10 digits divisible by 11
        ("SK 2992857890", True),
        ("SK7120000196", False),
        ("CZ98841009", True),  # Czech legal person: CZ + IČO
        ("CZ60491851", False),
        ("CZ18630138", True),
        ("DE123456789", True),  # other EU states: format only
        ("XX123", False),
    ],
)
def test_vat_id(vat_id, ok):
    assert is_valid_vat_id(vat_id) is ok


@pytest.mark.parametrize(
    ("printed", "gtin", "flags"),
    [
        ("2904012071349", "2904012071349", set()),
        ("EAN: 2904012072216", "2904012072216", set()),
        ("2904012073381", "2904012073381", set()),
        ("74912305874", "074912305874", {"padded"}),  # UPC-A printed without its leading zero
        ("2904012071340", None, {"check_digit"}),
        ("290401207134", None, {"check_digit"}),
        ("12345", None, {"length"}),
    ],
)
def test_normalize_gtin(printed, gtin, flags):
    result = normalize_gtin(printed)
    assert result.gtin == gtin
    assert result.flags == flags


@given(st.integers(0, 2**32))
def test_generated_identifiers_are_valid(seed):
    rng = random.Random(seed)
    assert is_valid_ico(generate_ico(rng))
    assert is_valid_sk_dic(generate_sk_dic(rng))
    ean = generate_ean13(rng, prefix="858")
    assert ean.startswith("858") and len(ean) == 13
    assert gtin_check_digit(ean[:-1]) == int(ean[-1])
    assert normalize_gtin(ean).flags == set()
