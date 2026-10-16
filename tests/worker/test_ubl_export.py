"""Peppol UBL export and the mock ERP's rules: a correct document passes, a broken one names
the rule it breaks."""

import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal as Dec

import pytest

from claimpilot_core_mock.ubl_rules import CBC, check, parse
from claimpilot_worker.export.ubl import Line, Party, UblInvoice, build

SUPPLIER = Party(
    "BioFlora s.r.o.", "98391267", "SK2995153513", "SK", "Laborecká 1", "Žilina", "010 01"
)
BUYER = Party("Lekárne Sever s.r.o.", "90882750", "SK2997673481", "SK")


def invoice(**kw) -> UblInvoice:
    base = dict(
        kind="invoice",
        number="260104417",
        issue_date=date(2025, 8, 20),
        due_date=date(2025, 9, 19),
        tax_point_date=date(2025, 8, 20),
        currency="EUR",
        supplier=SUPPLIER,
        buyer=BUYER,
        iban="SK89 0200 0000 0076 9943 1836",
        payment_id="260104417",
        order_number="OB25000001",
        delivery_note=None,
        original_number=None,
        reverse_charge=False,
        lines=[
            Line(Dec("2"), "ks", "Šampón", Dec("2.656"), Dec("5.31"), 23, "02904012073381", "0001"),
            Line(Dec("30"), "ks", "Sušienky", Dec("0.573"), Dec("17.19"), 19),
        ],
    )
    return UblInvoice(**(base | kw))


def rules(xml: bytes) -> set[str]:
    return {e["rule"] for e in check(parse(xml))[1]}


def test_a_correct_invoice_passes():
    assert rules(build(invoice())) == set()


def test_charges_prepayments_credit_notes_and_reverse_charge_pass():
    assert rules(build(invoice(charges=[("Doprava", Dec("4.90"), 23)]))) == set()
    assert rules(build(invoice(prepaid=Dec("10.00"), kind="proforma"))) == set()
    credit = invoice(
        kind="credit_note",
        original_number="250008600",
        lines=[Line(Dec("-3"), "ks", "Šampón", Dec("2.656"), Dec("-7.97"), 23)],
    )
    assert rules(build(credit)) == set()
    cz = Party("Lumina Cosmetics CZ s.r.o.", "45391289", "CZ45391289", "CZ")
    assert rules(build(invoice(supplier=cz, reverse_charge=True))) == set()


def test_the_type_codes():
    assert b">380<" in build(invoice()) and b">386<" in build(invoice(kind="proforma"))
    assert b">381<" in build(invoice(kind="credit_note", original_number="1"))


def _edit(xml: bytes, tag: str, value: str, nth: int = 0) -> bytes:
    root = ET.fromstring(xml)
    el = root.findall(f".//{CBC}{tag}")[nth]
    el.text = value
    return ET.tostring(root, encoding="utf-8")


@pytest.mark.parametrize(
    ("tag", "value", "rule"),
    [
        ("PayableAmount", "1.00", "BR-CO-16"),
        ("TaxInclusiveAmount", "99.99", "BR-CO-15"),
        ("LineExtensionAmount", "6.31", "PEPPOL-EN16931-R120"),  # the first line amount
        ("TaxAmount", "9.99", "BR-CO-14"),
        ("RegistrationName", "", "BR-06"),
        ("IdentificationCode", "", "BR-09"),
    ],
)
def test_a_broken_document_names_its_rule(tag, value, rule):
    xml = build(invoice())
    nth = 1 if tag == "LineExtensionAmount" else 0  # the first is the document total
    assert rule in rules(_edit(xml, tag, value, nth))


def test_a_wrong_iban_and_a_missing_original_are_refused():
    assert "IBAN" in rules(build(invoice(iban="SK63 1100 0000 0029 4006 8013")))
    assert "CN-ORIGINAL" in rules(build(invoice(kind="credit_note")))


def test_a_dtd_is_refused():
    with pytest.raises(ValueError, match="DTD"):
        parse(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')


@pytest.mark.parametrize(
    ("qty", "price", "net"),
    [(Dec("-1"), Dec("10.00"), Dec("-10.00")), (Dec("1"), Dec("-10.00"), Dec("-10.00"))],
)
def test_a_return_line_on_an_invoice_passes(qty, price, net):
    # Printed either way: a negative quantity, or a negative price (a discount line).
    lines = [*invoice().lines, Line(qty, "ks", "Vrátenie", price, net, 23)]
    assert rules(build(invoice(lines=lines))) == set()


def test_an_iban_with_dashes_is_refused_not_a_crash():
    assert "IBAN" in rules(build(invoice(iban="SK63-1100-0000-0029-4006-8012")))
