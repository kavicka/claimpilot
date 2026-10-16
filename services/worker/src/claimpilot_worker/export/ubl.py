"""Approved invoices as Peppol BIS Billing 3.0 documents (UBL 2.1, EN 16931), ADR-015.

Built from normalized, handler-approved values only, never from model output. A credit note is a
UBL CreditNote with a billing reference to the original. VAT categories: S (standard rate),
K (intra-Community supply, the VAT is the buyer's to account for). Line prices may carry more
than two decimals ("0,573"), so the line amount is the rounded product, as Peppol rule R120 has it.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CUSTOMIZATION = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
PROFILE = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
NS = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
for prefix, uri in (("cac", NS["cac"]), ("cbc", NS["cbc"])):
    ET.register_namespace(prefix, uri)
CENT = Decimal("0.01")
UNIT_CODES = {"ks": "H87", "kus": "H87", "": "H87", "pc": "H87", "kg": "KGM", "l": "LTR"}
EAS_VAT = {"SK": "9950", "CZ": "9929"}  # Peppol electronic address schemes: national VAT ids


@dataclass
class Party:
    name: str
    ico: str | None
    vat_id: str | None
    country: str
    street: str | None = None
    city: str | None = None
    zip: str | None = None


@dataclass
class Line:
    quantity: Decimal
    unit: str
    name: str
    net_price: Decimal  # per unit after discounts
    line_net: Decimal
    vat_rate: int
    gtin: str | None = None
    supplier_code: str | None = None


@dataclass
class UblInvoice:
    kind: str  # invoice | credit_note
    number: str
    issue_date: date
    due_date: date | None
    tax_point_date: date | None
    currency: str
    supplier: Party
    buyer: Party
    iban: str | None
    payment_id: str | None  # the variable symbol
    order_number: str | None
    delivery_note: str | None
    original_number: str | None
    reverse_charge: bool
    lines: list[Line] = field(default_factory=list)
    prepaid: Decimal = Decimal(0)
    # Fees printed outside the items (transport): document-level charges (label, amount, rate).
    charges: list[tuple[str, Decimal, int]] = field(default_factory=list)
    # The VAT per rate as the invoice prints it. An invoice may round VAT per line; the printed
    # amount is the one owed, so it is the one exported.
    printed_vat: dict[int, Decimal] = field(default_factory=dict)


def r2(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    prefix, name = tag.split(":")
    el = ET.SubElement(parent, f"{{{NS[prefix]}}}{name}", attrs)
    if text is not None:
        el.text = text
    return el


def _amount(parent: ET.Element, tag: str, value: Decimal, currency: str) -> None:
    _sub(parent, tag, f"{r2(value)}", currencyID=currency)


def _party(parent: ET.Element, tag: str, p: Party) -> None:
    party = _sub(_sub(parent, tag), "cac:Party")
    if p.vat_id:
        _sub(party, "cbc:EndpointID", p.vat_id, schemeID=EAS_VAT.get(p.country, "9950"))
    address = _sub(party, "cac:PostalAddress")
    if p.street:
        _sub(address, "cbc:StreetName", p.street)
    if p.city:
        _sub(address, "cbc:CityName", p.city)
    if p.zip:
        _sub(address, "cbc:PostalZone", p.zip)
    _sub(_sub(address, "cac:Country"), "cbc:IdentificationCode", p.country)
    if p.vat_id:
        scheme = _sub(party, "cac:PartyTaxScheme")
        _sub(scheme, "cbc:CompanyID", p.vat_id)
        _sub(_sub(scheme, "cac:TaxScheme"), "cbc:ID", "VAT")
    legal = _sub(party, "cac:PartyLegalEntity")
    _sub(legal, "cbc:RegistrationName", p.name)
    if p.ico:
        _sub(legal, "cbc:CompanyID", p.ico)


def _category(parent: ET.Element, tag: str, rate: int, reverse: bool) -> None:
    cat = _sub(parent, tag)
    _sub(cat, "cbc:ID", "K" if reverse else "S")
    _sub(cat, "cbc:Percent", str(rate))
    if reverse and tag == "cac:TaxCategory":
        _sub(cat, "cbc:TaxExemptionReasonCode", "VATEX-EU-IC")
    _sub(_sub(cat, "cac:TaxScheme"), "cbc:ID", "VAT")


def build(inv: UblInvoice) -> bytes:
    credit = inv.kind == "credit_note"
    # A credit note states its amounts as positive: the document type says they go back.
    sign = Decimal(-1) if credit else Decimal(1)
    root = ET.Element(f"{{{NS['cn' if credit else 'inv']}}}{'CreditNote' if credit else 'Invoice'}")
    _sub(root, "cbc:CustomizationID", CUSTOMIZATION)
    _sub(root, "cbc:ProfileID", PROFILE)
    _sub(root, "cbc:ID", inv.number)
    _sub(root, "cbc:IssueDate", inv.issue_date.isoformat())
    if inv.due_date and not credit:
        _sub(root, "cbc:DueDate", inv.due_date.isoformat())
    # 380 commercial invoice, 386 prepayment invoice (a proforma), 381 credit note
    code = "381" if credit else "386" if inv.kind == "proforma" else "380"
    _sub(root, "cbc:CreditNoteTypeCode" if credit else "cbc:InvoiceTypeCode", code)
    if inv.tax_point_date:
        _sub(root, "cbc:TaxPointDate", inv.tax_point_date.isoformat())
    _sub(root, "cbc:DocumentCurrencyCode", inv.currency)
    _sub(root, "cbc:BuyerReference", inv.order_number or inv.number)
    if inv.order_number:
        _sub(_sub(root, "cac:OrderReference"), "cbc:ID", inv.order_number)
    if credit and inv.original_number:
        ref = _sub(_sub(root, "cac:BillingReference"), "cac:InvoiceDocumentReference")
        _sub(ref, "cbc:ID", inv.original_number)
    if inv.delivery_note:
        _sub(_sub(root, "cac:DespatchDocumentReference"), "cbc:ID", inv.delivery_note)
    _party(root, "cac:AccountingSupplierParty", inv.supplier)
    _party(root, "cac:AccountingCustomerParty", inv.buyer)
    if inv.iban and not credit:
        means = _sub(root, "cac:PaymentMeans")
        _sub(means, "cbc:PaymentMeansCode", "58")  # SEPA credit transfer
        if inv.payment_id:
            _sub(means, "cbc:PaymentID", inv.payment_id)
        _sub(_sub(means, "cac:PayeeFinancialAccount"), "cbc:ID", inv.iban.replace(" ", ""))
    bases: dict[int, Decimal] = {}
    for ln in inv.lines:
        rate = 0 if inv.reverse_charge else ln.vat_rate  # one K subtotal, whatever was printed
        bases[rate] = bases.get(rate, Decimal(0)) + ln.line_net * sign
    line_total = sum((b for b in bases.values()), Decimal(0))
    charge_total = Decimal(0)
    for label, amount, rate in inv.charges:
        charge = _sub(root, "cac:AllowanceCharge")
        _sub(charge, "cbc:ChargeIndicator", "true")
        _sub(charge, "cbc:AllowanceChargeReason", label)
        _amount(charge, "cbc:Amount", amount * sign, inv.currency)
        _category(charge, "cac:TaxCategory", 0 if inv.reverse_charge else rate, inv.reverse_charge)
        key = 0 if inv.reverse_charge else rate
        bases[key] = bases.get(key, Decimal(0)) + amount * sign
        charge_total += amount * sign
    tax_total = _sub(root, "cac:TaxTotal")
    vat_sum = Decimal(0)
    subtotals = []
    for rate, base in sorted(bases.items()):
        if inv.reverse_charge:
            vat = Decimal(0)
        elif rate in inv.printed_vat:
            vat = abs(inv.printed_vat[rate]) * (1 if base >= 0 else -1)
        else:
            vat = r2(base * rate / 100)
        vat_sum += vat
        subtotals.append((rate, base, vat))
    _amount(tax_total, "cbc:TaxAmount", vat_sum, inv.currency)
    for rate, base, vat in subtotals:
        sub = _sub(tax_total, "cac:TaxSubtotal")
        _amount(sub, "cbc:TaxableAmount", base, inv.currency)
        _amount(sub, "cbc:TaxAmount", vat, inv.currency)
        _category(sub, "cac:TaxCategory", rate if not inv.reverse_charge else 0, inv.reverse_charge)
    net = line_total + charge_total
    totals = _sub(root, "cac:LegalMonetaryTotal")
    _amount(totals, "cbc:LineExtensionAmount", line_total, inv.currency)
    _amount(totals, "cbc:TaxExclusiveAmount", net, inv.currency)
    _amount(totals, "cbc:TaxInclusiveAmount", net + vat_sum, inv.currency)
    if charge_total:
        _amount(totals, "cbc:ChargeTotalAmount", charge_total, inv.currency)
    if inv.prepaid:
        _amount(totals, "cbc:PrepaidAmount", abs(inv.prepaid), inv.currency)
    _amount(totals, "cbc:PayableAmount", net + vat_sum - abs(inv.prepaid), inv.currency)
    for i, ln in enumerate(inv.lines, start=1):
        line = _sub(root, "cac:CreditNoteLine" if credit else "cac:InvoiceLine")
        _sub(line, "cbc:ID", str(i))
        unit = UNIT_CODES.get(ln.unit.lower().rstrip("."), "H87")
        qty_tag = "cbc:CreditedQuantity" if credit else "cbc:InvoicedQuantity"
        _sub(line, qty_tag, f"{abs(ln.quantity).normalize():f}", unitCode=unit)
        _amount(line, "cbc:LineExtensionAmount", ln.line_net * sign, inv.currency)
        item = _sub(line, "cac:Item")
        _sub(item, "cbc:Name", ln.name)
        if ln.supplier_code:
            _sub(_sub(item, "cac:SellersItemIdentification"), "cbc:ID", ln.supplier_code)
        if ln.gtin:
            _sub(_sub(item, "cac:StandardItemIdentification"), "cbc:ID", ln.gtin, schemeID="0160")
        _category(
            item,
            "cac:ClassifiedTaxCategory",
            0 if inv.reverse_charge else ln.vat_rate,
            inv.reverse_charge,
        )
        _sub(
            _sub(line, "cac:Price"),
            "cbc:PriceAmount",
            f"{abs(ln.net_price).normalize():f}",
            currencyID=inv.currency,
        )
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
