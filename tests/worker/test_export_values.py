"""The UBL builder's input (export/values.py): what cannot be read stops the export with the
field's name; nothing is filled in with a default that moves money."""

import pytest

from claimpilot_worker.export.values import ExportError, from_values

HEADER = {
    "invoice_number": "260104417",
    "issue_date": "20.08.2025",
    "currency": "EUR",
    "supplier_name": "BioFlora s.r.o.",
    "buyer_name": "Lekárne Sever s.r.o.",
    "supplier_vat_id": "SK2995153513",
    "buyer_vat_id": "SK2997673481",
    "recap[0].rate": "23%",
    "recap[0].base": "5,31",
    "recap[0].vat": "1,22",
}
LINE = {"quantity": "2", "line_net": "5,31", "vat_rate": "23%", "name": "Šampón"}


def build(header=HEADER, lines=(LINE,), **kw):
    return from_values(
        dict(header),
        [dict(ln) for ln in lines],
        kind="invoice",
        supplier_record=None,
        buyer_record=None,
        **kw,
    )


def test_a_clean_invoice_builds():
    inv = build()
    assert inv.currency == "EUR" and inv.lines[0].vat_rate == 23


@pytest.mark.parametrize("bad", ["", "abc", "99%", "7%"])
def test_a_vat_rate_that_cannot_be_read_or_does_not_exist_stops_the_export(bad):
    # An unreadable rate used to export as 0 %.
    header = {k: v for k, v in HEADER.items() if not k.startswith("recap")}
    with pytest.raises(ExportError) as exc:
        build(header, [dict(LINE, vat_rate=bad)])
    assert exc.value.field == "lines[1].vat_rate"


def test_a_line_without_a_rate_takes_the_only_rate_of_the_recap():
    assert build(lines=[{k: v for k, v in LINE.items() if k != "vat_rate"}]).lines[0].vat_rate == 23


def test_a_line_without_a_rate_and_two_recap_rates_stops_the_export():
    header = HEADER | {"recap[1].rate": "19%", "recap[1].base": "1,00", "recap[1].vat": "0,19"}
    with pytest.raises(ExportError) as exc:
        build(header, [{k: v for k, v in LINE.items() if k != "vat_rate"}])
    assert exc.value.field == "lines[1].vat_rate"


def test_reverse_charge_needs_no_rate_on_the_lines():
    header = {k: v for k, v in HEADER.items() if not k.startswith("recap")} | {
        "reverse_charge": "yes"
    }
    assert (
        build(header, [{k: v for k, v in LINE.items() if k != "vat_rate"}]).lines[0].vat_rate == 0
    )


@pytest.mark.parametrize("currency", [None, "", "XXX"])
def test_a_missing_or_unknown_currency_stops_the_export(currency):
    # A missing currency used to export as EUR.
    header = {k: v for k, v in HEADER.items() if k != "currency"} | (
        {"currency": currency} if currency is not None else {}
    )
    with pytest.raises(ExportError) as exc:
        build(header)
    assert exc.value.field == "currency"


def test_the_allowed_rates_come_from_the_caller():
    with pytest.raises(ExportError):
        build(vat_rates=frozenset({0, 5}))
    assert build(vat_rates=frozenset({0, 23})).lines[0].vat_rate == 23
