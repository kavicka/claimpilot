"""Invoice validation in code (validation/invoice.py): every arithmetic and identity rule, each
failure pointing at the fields it concerns. Values are given as printed, like extraction does."""

import pytest

from claimpilot_worker.validation.invoice import Ours, validate

OURS = Ours(icos={"90882750"}, vat_ids={"SK2997673481"})
GOOD_SK = {
    "invoice_number": "260104417",
    "issue_date": "20.08.2025",
    "tax_point_date": "20.08.2025",
    "due_date": "19.09.2025",
    "supplier_ico": "98391267",
    "supplier_vat_id": "SK2995153513",
    "supplier_iban": "SK89 0200 0000 0076 9943 1836",
    "buyer_ico": "90882750",
    "buyer_vat_id": "SK2997673481",
    "currency": "EUR",
    "total_net": "29,31",
    "total_vat": "6,74",
    "total": "36,05",
    "amount_due": "36,05",
    "recap[0].rate": "23%",
    "recap[0].base": "29,31",
    "recap[0].vat": "6,74",
}
LINES = [
    {"quantity": "2", "unit_price": "3,32", "discount_pct": "20,00%", "line_net": "5,31", "vat_rate": "23%", "vat_amount": "1,22", "line_gross": "6,53"},
    {"quantity": "6", "unit_price": "5,00", "discount_pct": "20,00%", "line_net": "24,00", "vat_rate": "23%", "vat_amount": "5,52", "line_gross": "29,52"},
]  # fmt: skip


def failed(result) -> dict[str, list[str]]:
    return {c.name: c.fields for c in result.checks if not c.ok}


def test_a_clean_invoice_passes_every_check():
    result = validate(GOOD_SK, LINES, OURS, pages_present=1)
    assert failed(result) == {}
    assert not result.needs_info


def test_line_math_points_at_the_line():
    lines = [dict(LINES[0], line_net="5,41"), LINES[1]]
    bad = failed(validate(GOOD_SK, lines, OURS, pages_present=1))
    assert "line_math" in bad and "lines[1].line_net" in bad["line_math"]


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ({"quantity": "30,000", "unit_price": "0,573", "line_net": "17,19"}, True),  # 3 decimals
        ({"quantity": "200", "unit_price": "22,56", "net_unit_price": "13,53", "line_net": "2.706,00"}, True),
        ({"quantity": "10", "unit_price": "20,00", "struct_discount_pct": "10,00%", "promo_discount_pct": "5,00%", "line_net": "171,00"}, True),
        ({"quantity": "-3,00", "unit_price": "1,52", "line_net": "-4,56"}, True),  # credit note
        ({"quantity": "12", "unit_price": "1,10", "line_net": "13,30"}, False),
    ],
)  # fmt: skip
def test_line_math_forms(line, ok):
    result = validate({}, [line], OURS, pages_present=1)
    assert next(c for c in result.checks if c.name == "line_math").ok is ok


def test_recap_and_totals():
    header = dict(GOOD_SK, total="36,15")
    bad = failed(validate(header, LINES, OURS, pages_present=1))
    assert set(bad) == {"total"}
    header = dict(GOOD_SK, **{"recap[0].base": "29,41"})
    assert "recap_base" in failed(validate(header, LINES, OURS, pages_present=1))


def test_amount_due_after_an_advance():
    header = dict(GOOD_SK, amount_due="16,05", proforma_settled="-20,00", proforma_number="ZF1")
    assert failed(validate(header, LINES, OURS, pages_present=1)) == {}
    header["amount_due"] = "36,05"
    assert "amount_due" in failed(validate(header, LINES, OURS, pages_present=1))


def test_identifiers():
    header = dict(GOOD_SK, supplier_ico="52234071", supplier_iban="SK63 1100 0000 0029 4006 8013")
    bad = failed(validate(header, LINES, OURS, pages_present=1))
    assert {"supplier_ico", "supplier_iban"} <= set(bad)


def test_the_buyer_must_be_one_of_ours():
    header = dict(GOOD_SK, buyer_ico="91583632", buyer_vat_id="SK2998051309")
    assert "buyer_is_ours" in failed(validate(header, LINES, OURS, pages_present=1))


def test_zero_vat_needs_a_reverse_charge_note_and_a_foreign_supplier():
    lines = [{"quantity": "1", "unit_price": "100,00", "line_net": "100,00", "vat_rate": "0"}]
    header = dict(
        GOOD_SK,
        supplier_vat_id="CZ98841009",
        supplier_ico="98841009",
        total_net="100,00",
        total_vat="0,00",
        total="100,00",
        amount_due="100,00",
        **{"recap[0].rate": "0", "recap[0].base": "100,00", "recap[0].vat": "0,00"},
    )
    header["reverse_charge"] = "Intra-Community supply, Art. 138"
    assert failed(validate(header, lines, OURS, pages_present=1)) == {}
    del header["reverse_charge"]
    assert "vat_regime" in failed(validate(header, lines, OURS, pages_present=1))
    header |= {"reverse_charge": "oslobodené", "supplier_vat_id": "SK2995153513"}
    assert "vat_regime" in failed(validate(header, lines, OURS, pages_present=1))


def test_due_date_not_before_issue():
    header = dict(GOOD_SK, due_date="19.07.2025")
    assert "date_order" in failed(validate(header, LINES, OURS, pages_present=1))


def test_missing_pages_need_information():
    header = dict(GOOD_SK, page_note="strana 1 z 9")
    result = validate(header, LINES, OURS, pages_present=1)
    assert "pages_complete" in failed(result)
    assert result.needs_info
    assert not validate(
        dict(GOOD_SK, page_note="Strana 1/1"), LINES, OURS, pages_present=1
    ).needs_info


def test_a_second_currency_total_matches_the_rate():
    header = dict(GOOD_SK, fx_rate="24,92", second_currency_total="898,37")
    assert failed(validate(header, LINES, OURS, pages_present=1)) == {}
    header["second_currency_total"] = "908,37"
    assert "second_currency" in failed(validate(header, LINES, OURS, pages_present=1))


def test_a_credit_note_has_negative_amounts_and_an_original():
    lines = [{"quantity": "-3,00", "unit_price": "1,52", "line_net": "-4,56", "vat_rate": "19"}]
    header = {
        "currency": "EUR",
        "total_net": "-4,56",
        "total_vat": "-0,87",
        "total": "-5,43",
        "amount_due": "-5,43",
        "recap[0].rate": "19%",
        "recap[0].base": "-4,56",
        "recap[0].vat": "-0,87",
    }
    result = validate(header, lines, OURS, pages_present=1, kind="credit_note")
    assert "credit_note_original" in failed(result)
    header["original_invoice_number"] = "260311007"
    assert failed(validate(header, lines, OURS, pages_present=1, kind="credit_note")) == {}
    header["total"] = "5,43"
    assert "credit_note_sign" in failed(
        validate(header, lines, OURS, pages_present=1, kind="credit_note")
    )


def test_ean_check_digit():
    lines = [dict(LINES[0], ean="2904012071340"), dict(LINES[1], ean="74912305874")]
    result = validate(GOOD_SK, lines, OURS, pages_present=1)
    ean = [c for c in result.checks if c.name == "ean"]
    assert [c.ok for c in ean] == [False, True]  # the 11-digit UPC is valid once padded
    assert ean[1].detail == "padded"


def test_unreadable_values_fail_their_check_instead_of_passing():
    lines = [dict(LINES[0], line_net="5,3l")]  # OCR read a letter
    assert "line_math" in failed(validate(GOOD_SK, lines, OURS, pages_present=1))


# --- a missing line or total must not pass --------------------------------------------------

NO_RECAP = {k: v for k, v in GOOD_SK.items() if not k.startswith("recap") and k != "total_net"}


def test_a_line_left_out_fails_the_lines_total_without_a_recap():
    # Scans print no recap: the total is the only thing to hold the lines against.
    bad = failed(validate(NO_RECAP, LINES[:1], OURS, pages_present=1))
    assert "lines_total" in bad


def test_the_lines_total_holds_for_a_complete_invoice_without_a_recap():
    assert failed(validate(NO_RECAP, LINES, OURS, pages_present=1)) == {}


def test_a_line_left_out_fails_against_the_printed_net_total():
    header = {k: v for k, v in GOOD_SK.items() if not k.startswith("recap")}
    bad = failed(validate(header, LINES[:1], OURS, pages_present=1))
    assert "lines_total" in bad and "total_net" in bad["lines_total"]


def test_a_line_without_quantity_or_amount_is_incomplete():
    lines = [{"name": "Šampón", "vat_rate": "23%"}, LINES[1]]
    bad = failed(validate(GOOD_SK, lines, OURS, pages_present=1))
    assert bad["line_complete"] == ["lines[1].quantity", "lines[1].line_net"]


def test_an_unread_final_amount_fails():
    header = {k: v for k, v in GOOD_SK.items() if k not in ("total", "amount_due")}
    bad = failed(validate(header, LINES, OURS, pages_present=1))
    assert bad["total"] == ["total", "amount_due"]


def test_the_amount_due_alone_is_a_final_amount():
    header = {k: v for k, v in GOOD_SK.items() if k != "total"}
    assert failed(validate(header, LINES, OURS, pages_present=1)) == {}


# --- money safety: VAT rate, currency, sign, tolerance --------------------------------------------


def test_a_vat_rate_that_does_not_exist_fails_the_line():
    lines = [dict(LINES[0], vat_rate="99%"), LINES[1]]
    bad = failed(validate(GOOD_SK, lines, OURS, pages_present=1))
    assert bad["vat_rate"] == ["lines[1].vat_rate"]


def test_a_line_without_a_rate_takes_the_only_rate_of_the_recap():
    lines = [
        {k: v for k, v in ln.items() if k not in ("vat_rate", "vat_amount", "line_gross")}
        for ln in LINES
    ]
    assert "vat_rate" not in failed(validate(GOOD_SK, lines, OURS, pages_present=1))


def test_a_line_without_a_rate_and_two_rates_in_the_recap_fails():
    header = dict(GOOD_SK) | {
        "recap[1].rate": "19%",
        "recap[1].base": "1,00",
        "recap[1].vat": "0,19",
    }
    lines = [{k: v for k, v in ln.items() if k != "vat_rate"} for ln in LINES]
    assert "vat_rate" in failed(validate(header, lines, OURS, pages_present=1))


def test_a_missing_or_unknown_currency_fails():
    for header in (
        {k: v for k, v in GOOD_SK.items() if k != "currency"},
        dict(GOOD_SK, currency="XXX"),
    ):
        assert failed(validate(header, LINES, OURS, pages_present=1))["currency"] == ["currency"]
    assert "currency" not in failed(
        validate(dict(GOOD_SK, currency="CZK"), LINES, OURS, pages_present=1)
    )


def test_a_negative_total_on_an_invoice_fails_but_not_on_a_credit_note():
    header = dict(GOOD_SK, total="-36,05", amount_due="-36,05", original_invoice_number="250008600")
    assert "amount_sign" in failed(validate(header, LINES, OURS, pages_present=1))
    assert "amount_sign" not in failed(
        validate(header, LINES, OURS, pages_present=1, kind="credit_note")
    )


def test_a_long_invoice_without_a_recap_does_not_get_a_wider_tolerance():
    # 300 lines of 1.00: 3 cents missing from the total must be seen, not absorbed by 300 x 0.01.
    lines = [
        {"quantity": "1", "unit_price": "1,00", "line_net": "1,00", "vat_rate": "0%"}
        for _ in range(300)
    ]
    header = {
        k: v
        for k, v in GOOD_SK.items()
        if not k.startswith("recap") and k not in ("total_net", "total_vat")
    }
    header |= {"total": "300,00", "amount_due": "300,00"}
    assert "lines_total" not in failed(validate(header, lines, OURS, pages_present=1))
    header |= {"total": "299,97", "amount_due": "299,97"}
    assert "lines_total" in failed(validate(header, lines, OURS, pages_present=1))


def test_vat_rounded_per_line_or_per_rate_both_pass_without_a_recap():
    # 3 lines of 0.10 at 23 %: per line 3 x 0.02 = 0.06, per rate round(0.30 x 0.23) = 0.07.
    lines = [
        {"quantity": "1", "unit_price": "0,10", "line_net": "0,10", "vat_rate": "23%"}
        for _ in range(3)
    ]
    base = {
        k: v
        for k, v in GOOD_SK.items()
        if not k.startswith("recap") and k not in ("total_net", "total_vat")
    }
    for total in ("0,36", "0,37"):
        header = base | {"total": total, "amount_due": total}
        assert "lines_total" not in failed(validate(header, lines, OURS, pages_present=1))
    header = base | {"total": "0,39", "amount_due": "0,39"}
    assert "lines_total" in failed(validate(header, lines, OURS, pages_present=1))


def test_a_missing_currency_is_not_blamed_when_pages_are_missing():
    header = {k: v for k, v in GOOD_SK.items() if k != "currency"} | {"page_note": "strana 1 z 3"}
    result = validate(header, LINES, OURS, pages_present=1)
    assert result.needs_info and "currency" not in failed(result)
