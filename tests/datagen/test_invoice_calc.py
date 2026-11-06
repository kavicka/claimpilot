"""The generator's invoice arithmetic and number printing, checked against lines of the samples."""

from datetime import date
from decimal import Decimal

import pytest

from claimpilot_datagen.invoices.calc import compute
from claimpilot_datagen.invoices.fmt import STYLES, number
from claimpilot_datagen.invoices.model import (
    DocKind,
    Fee,
    Invoice,
    Layout,
    Line,
    Party,
    Product,
    VatMethod,
)

D = Decimal  # short, so the sample lines read like the invoices
PARTY = Party(
    "p",
    "Firma s.r.o.",
    "Ulica 1",
    "811 01",
    "Bratislava",
    "SK",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
)


def product(rate: int) -> Product:
    return Product("2904012071349", "C1", "Tovar", rate, D("1"))


def invoice(layout: Layout, lines: list[Line], **kw) -> Invoice:
    d = date(2025, 4, 10)
    return compute(
        Invoice(
            "I1", "dev", layout, DocKind.INVOICE, "1", PARTY, PARTY, "Senec", d, d, d, lines, **kw
        )
    )


def test_pohoda_discount_and_vat_per_line_as_on_the_sample():
    inv = invoice(
        Layout.POHODA,
        [
            Line(product(23), D(2), D("3.32"), discount_pct=D(20)),
            Line(product(23), D(6), D("3.32"), discount_pct=D(20)),
        ],
    )
    a, b = inv.lines
    assert (a.line_net, a.vat_amount, a.line_gross) == (D("5.31"), D("1.22"), D("6.53"))
    assert (b.line_net, b.vat_amount, b.line_gross) == (D("15.94"), D("3.67"), D("19.61"))
    assert inv.vat_method is VatMethod.PER_LINE
    assert inv.recap[0].vat == D("4.89")  # sum of the lines, not round(21.25 x 0.23) = 4.89


def test_vat_per_line_can_differ_from_vat_per_rate():
    lines = [Line(product(23), D(1), D("0.05")) for _ in range(10)]  # 10 x round(0.0115) = 0.10
    per_line = invoice(Layout.POHODA, [Line(ln.product, ln.qty, ln.unit_price) for ln in lines])
    per_rate = invoice(Layout.TANGRAM, lines)
    assert per_line.total_vat == D("0.10")
    assert per_rate.total_vat == D("0.12")  # round(0.50 x 0.23 = 0.115)


def test_tangram_three_decimal_prices_as_on_the_sample():
    inv = invoice(
        Layout.TANGRAM,
        [Line(product(19), D(30), D("0.573")), Line(product(19), D(15), D("0.927"))],
    )
    a, b = inv.lines
    assert (a.line_net, a.gross_unit_price) == (D("17.19"), D("0.6819"))
    assert b.line_net == D("13.91")  # 13.905 rounds half up


def test_tangram_recap_vat_from_the_base():
    inv = invoice(Layout.TANGRAM, [Line(product(19), D(1), D("5812.40"))])
    assert (inv.recap[0].base, inv.recap[0].vat, inv.total) == (
        D("5812.40"),
        D("1104.36"),
        D("6916.76"),
    )


def test_sap_discounts_compound_on_the_unit_price():
    ln = Line(product(23), D(10), D("20.00"), struct_disc_pct=D(10), promo_disc_pct=D(5))
    inv = invoice(Layout.SAP, [ln])
    assert ln.net_unit_price == D("17.10")  # 20 x 0.9 x 0.95
    assert ln.line_net == D("171.00")
    assert inv.total == D("210.33")


def test_reverse_charge_prints_zero_vat():
    inv = invoice(Layout.SCAN_EN, [Line(product(23), D(200), D("152.37"))], reverse_charge=True)
    assert inv.lines[0].vat_rate == 0
    assert inv.total == inv.total_net == D("30474.00")


def test_fee_outside_the_items_is_taxed_and_added():
    inv = invoice(
        Layout.POHODA,
        [Line(product(23), D(1), D("100"))],
        fees=[Fee("transport", "Doprava", D("5.00"), 23, included=False)],
    )
    assert inv.total_net == D("105.00")
    assert inv.total_vat == D("24.15")


def test_included_fee_changes_nothing():
    inv = invoice(
        Layout.WHOLESALE,
        [Line(product(23), D(1), D("100"))],
        fees=[Fee("recycling", "Recyklačný poplatok", D("3.36"), 23, included=True)],
    )
    assert inv.total == D("123.00")


def test_credit_note_lines_are_negative():
    inv = invoice(Layout.WHOLESALE, [Line(product(19), D(-3), D("1.52"))])
    assert inv.total == D("-5.43")  # -4.56 base, -0.87 VAT (half up away from zero)


def test_proforma_settlement_lowers_the_amount_due():
    inv = invoice(Layout.TANGRAM, [Line(product(19), D(1), D("100"))], proforma_settled=D("50.00"))
    assert (inv.total, inv.amount_due) == (D("119.00"), D("69.00"))


@pytest.mark.parametrize(
    ("value", "decimals", "thousands", "printed"),
    [
        (D("41218.37"), 4, ".", "41.218,3700"),
        (D("5812.40"), 2, " ", "5 812,40"),
        (D("4512"), 2, ".", "4.512,00"),
        (D("30"), 3, " ", "30,000"),
        (D("200"), 0, " ", "200"),
        (D("-881.04"), 2, " ", "-881,04"),
        (D("0.573"), 3, " ", "0,573"),
    ],
)
def test_number_printing(value, decimals, thousands, printed):
    assert number(value, decimals, thousands) == printed


def test_styles_cover_every_layout():
    assert set(STYLES) == set(Layout)
