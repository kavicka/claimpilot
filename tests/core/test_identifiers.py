import random
from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from claimpilot_core.identifiers import (
    format_iban,
    generate_rodne_cislo,
    generate_sk_iban,
    is_valid_iban,
    parse_rodne_cislo,
)

# --- rodné číslo -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "born", "female"),
    [
        ("850101/0001", date(1985, 1, 1), False),  # plain male
        ("8511010002", date(1985, 11, 1), False),  # without the slash
        ("905605/0003", date(1990, 6, 5), True),  # +50 month for women
        ("042101/0007", date(2004, 1, 1), False),  # Czech +20 offset since 2004
        ("047101/0001", date(2004, 1, 1), True),  # Czech +70 offset for women
    ],
)
def test_valid_rodne_cislo_parses_birth_date_and_sex(value, born, female):
    parsed = parse_rodne_cislo(value)
    assert parsed is not None
    assert parsed.birth_date == born
    assert parsed.female is female


def test_remainder_ten_with_check_digit_zero_is_valid_before_1985():
    # first nine digits 780123123 % 11 == 10, so the check digit is 0 (numbers issued before 1985)
    assert int("780123123") % 11 == 10
    assert parse_rodne_cislo("780123/1230") is not None


def test_remainder_ten_rule_does_not_apply_from_1985():
    first9 = next(
        f"8601{d:02d}{s:03d}"
        for d in range(1, 29)
        for s in range(1000)
        if int(f"8601{d:02d}{s:03d}") % 11 == 10
    )
    assert parse_rodne_cislo(f"{first9[:6]}/{first9[6:]}0") is None


def test_nine_digit_number_before_1954_has_no_check_digit():
    parsed = parse_rodne_cislo("520315/123")
    assert parsed is not None
    assert parsed.birth_date == date(1952, 3, 15)


def test_nine_digit_number_after_1954_is_invalid():
    assert parse_rodne_cislo("620315/123") is None


@pytest.mark.parametrize(
    "value",
    [
        "850101/0002",  # checksum
        "851301/0000",  # month 13, checksum valid
        "850230/0004",  # 30 February, checksum valid
        "85010100",  # too short
        "abcdef/ghij",
        "",
    ],
)
def test_invalid_rodne_cislo_is_rejected(value):
    assert parse_rodne_cislo(value) is None


@given(
    born=st.dates(min_value=date(1954, 1, 1), max_value=date(2025, 12, 31)),
    female=st.booleans(),
    czech_offset=st.booleans(),
    seed=st.integers(0, 10_000),
)
def test_generated_rodne_cislo_round_trips(born, female, czech_offset, seed):
    rc = generate_rodne_cislo(
        born,
        female=female,
        rng=random.Random(seed),
        czech_offset=czech_offset and born.year >= 2004,
    )
    parsed = parse_rodne_cislo(rc)
    assert parsed is not None
    assert parsed.birth_date == born
    assert parsed.female is female
    assert int(rc.replace("/", "")) % 11 == 0


# --- IBAN ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "SK3112000000198742637541",
        "SK31 1200 0000 1987 4263 7541",
        "DE89370400440532013000",
        "AT611904300234573201",
        "CZ6508000000192000145399",
    ],
)
def test_valid_ibans(value):
    assert is_valid_iban(value)


@pytest.mark.parametrize(
    "value",
    [
        "SK3112000000198742637542",  # one digit off
        "SK311200000019874263754",  # SK must be 24 characters
        "XX3112000000198742637541",  # unknown country
        "",
    ],
)
def test_invalid_ibans(value):
    assert not is_valid_iban(value)


@given(seed=st.integers(0, 100_000))
def test_generated_sk_iban_is_valid(seed):
    iban = generate_sk_iban(random.Random(seed))
    assert iban.startswith("SK")
    assert len(iban) == 24
    assert is_valid_iban(iban)
    assert is_valid_iban(format_iban(iban))


def test_format_iban_groups_by_four():
    assert format_iban("SK3112000000198742637541") == "SK31 1200 0000 1987 4263 7541"
