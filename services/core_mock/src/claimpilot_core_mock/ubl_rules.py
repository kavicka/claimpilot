"""The business rules the mock ERP applies to an incoming UBL invoice or credit note.

A subset of EN 16931 (BR-*) and Peppol BIS Billing 3.0 (PEPPOL-EN16931-R*) that covers what an
invoice from this pipeline can get wrong: required parties and dates, the totals, the VAT
breakdown per category and rate, the line amounts, the payment account. The full UBL schema and
Schematron sets are not run here; each refusal names its rule and the field.
"""

import xml.etree.ElementTree as ET
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CAC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2}"
CBC = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
ROOTS = {
    "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice": "invoice",
    "{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote": "credit_note",
}
CENT = Decimal("0.01")
COUNTRY = "Party/PostalAddress/Country/IdentificationCode"


def _p(path: str) -> str:
    return "/".join(
        (CAC if part[0].isupper() and part not in CBC_NAMES else CBC) + part
        for part in path.split("/")
    )


CBC_NAMES = {
    "ID", "IssueDate", "DueDate", "InvoiceTypeCode", "CreditNoteTypeCode", "DocumentCurrencyCode",
    "BuyerReference", "CustomizationID", "ProfileID", "RegistrationName", "IdentificationCode",
    "CompanyID", "TaxAmount", "Amount", "ChargeIndicator", "ChargeTotalAmount",
    "AllowanceTotalAmount", "AllowanceChargeReason", "TaxableAmount", "Percent",
    "LineExtensionAmount",
    "TaxExclusiveAmount", "TaxInclusiveAmount", "PrepaidAmount", "PayableAmount",
    "PaymentMeansCode", "InvoicedQuantity", "CreditedQuantity", "PriceAmount", "Name",
    "EndpointID", "TaxPointDate", "PaymentID", "TaxExemptionReasonCode",
}  # fmt: skip


def _text(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    found = el.find(_p(path))
    return found.text.strip() if found is not None and found.text else None


def _dec(el: ET.Element | None, path: str) -> Decimal | None:
    t = _text(el, path)
    try:
        return Decimal(t) if t is not None else None
    except InvalidOperation:
        return None


def r2(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _iban_ok(iban: str) -> bool:
    s = iban.replace(" ", "").upper()
    if len(s) < 15 or not s[:2].isalpha() or not s.isascii() or not s.isalnum():
        return False
    n = int("".join(str(int(c, 36)) for c in s[4:] + s[:4]))
    return n % 97 == 1


def parse(body: bytes) -> ET.Element:
    if b"<!DOCTYPE" in body[:2048].upper() or b"<!ENTITY" in body.upper():
        raise ValueError("DTDs and entities are not accepted")
    # Without a DTD there are no entities to expand: the attacks defusedxml guards against
    # (billion laughs, external entities) need one, and it was refused above.
    return ET.fromstring(body)  # noqa: S314


def check(root: ET.Element) -> tuple[str | None, list[dict[str, Any]]]:
    """(document kind, errors). No errors means the document is accepted."""
    errors: list[dict[str, Any]] = []

    def err(rule: str, field: str, message: str) -> None:
        errors.append({"rule": rule, "field": field, "message": message})

    kind = ROOTS.get(root.tag)
    if kind is None:
        err("UBL", "root", "not a UBL Invoice or CreditNote")
        return None, errors
    credit = kind == "credit_note"
    for rule, path, name in [
        ("BR-01", "CustomizationID", "specification identifier"),
        ("BR-02", "ID", "invoice number"),
        ("BR-03", "IssueDate", "issue date"),
        ("BR-04", "CreditNoteTypeCode" if credit else "InvoiceTypeCode", "type code"),
        ("BR-05", "DocumentCurrencyCode", "currency"),
        ("BR-06", "AccountingSupplierParty/Party/PartyLegalEntity/RegistrationName", "seller name"),
        ("BR-07", "AccountingCustomerParty/Party/PartyLegalEntity/RegistrationName", "buyer name"),
        ("BR-09", f"AccountingSupplierParty/{COUNTRY}", "seller country"),
        ("BR-11", f"AccountingCustomerParty/{COUNTRY}", "buyer country"),
    ]:  # fmt: skip
        if not _text(root, path):
            err(rule, path, f"the {name} is missing")
    if not _text(root, "BuyerReference") and not _text(root, "OrderReference/ID"):
        err(
            "PEPPOL-EN16931-R003",
            "BuyerReference",
            "a buyer reference or an order reference is required",
        )
    if credit and not _text(root, "BillingReference/InvoiceDocumentReference/ID"):
        err("CN-ORIGINAL", "BillingReference", "a credit note names the invoice it corrects")

    line_tag = _p("CreditNoteLine" if credit else "InvoiceLine")
    lines = root.findall(line_tag)
    if not lines:
        err("BR-16", line_tag, "at least one line is required")
    line_sum = Decimal(0)
    per_category: dict[tuple[str, str], Decimal] = {}
    for ln in lines:
        lid = _text(ln, "ID") or "?"
        amount = _dec(ln, "LineExtensionAmount")
        qty = _dec(ln, "CreditedQuantity" if credit else "InvoicedQuantity")
        price = _dec(ln, "Price/PriceAmount")
        if amount is None or qty is None or price is None:
            err("BR-24", f"line {lid}", "line amount, quantity and net price are required")
            continue
        if r2(qty * price) != amount:
            err("PEPPOL-EN16931-R120", f"line {lid}", f"{qty} x {price} is not {amount}")
        line_sum += amount
        cat = (
            _text(ln, "Item/ClassifiedTaxCategory/ID") or "?",
            _text(ln, "Item/ClassifiedTaxCategory/Percent") or "0",
        )
        per_category[cat] = per_category.get(cat, Decimal(0)) + amount  # fmt: skip

    totals = root.find(_p("LegalMonetaryTotal"))
    line_ext = _dec(totals, "LineExtensionAmount")
    tax_excl = _dec(totals, "TaxExclusiveAmount")
    tax_incl = _dec(totals, "TaxInclusiveAmount")
    prepaid = _dec(totals, "PrepaidAmount") or Decimal(0)
    payable = _dec(totals, "PayableAmount")
    tax_amount = _dec(root, "TaxTotal/TaxAmount") or Decimal(0)
    if line_ext is None or line_ext != line_sum:
        err("BR-CO-10", "LegalMonetaryTotal/LineExtensionAmount", f"lines sum to {line_sum}")
    charges = _dec(totals, "ChargeTotalAmount") or Decimal(0)
    allowances = _dec(totals, "AllowanceTotalAmount") or Decimal(0)
    charge_sum = Decimal(0)
    for ch in root.findall(_p("AllowanceCharge")):
        amount = _dec(ch, "Amount") or Decimal(0)
        indicator = (_text(ch, "ChargeIndicator") or "").lower() == "true"
        charge_sum += amount if indicator else -amount
        cat = (_text(ch, "TaxCategory/ID") or "?", _text(ch, "TaxCategory/Percent") or "0")
        per_category[cat] = per_category.get(cat, Decimal(0)) + (amount if indicator else -amount)
    if charge_sum != charges - allowances:
        err("BR-CO-11", "LegalMonetaryTotal/ChargeTotalAmount", "must be the sum of the charges")
    if tax_excl is None or line_ext is None or tax_excl != line_ext + charges - allowances:
        err(
            "BR-CO-13",
            "LegalMonetaryTotal/TaxExclusiveAmount",
            "lines plus charges less allowances",
        )
    if tax_incl is None or tax_excl is None or tax_incl != tax_excl + tax_amount:
        err(
            "BR-CO-15",
            "LegalMonetaryTotal/TaxInclusiveAmount",
            "must be the amount without VAT plus VAT",
        )
    if payable is None or tax_incl is None or payable != tax_incl - prepaid:
        err(
            "BR-CO-16",
            "LegalMonetaryTotal/PayableAmount",
            "must be the total less the prepaid amount",
        )

    subtotal_sum = Decimal(0)
    for sub in root.findall(_p("TaxTotal/TaxSubtotal")):
        taxable = _dec(sub, "TaxableAmount")
        tax = _dec(sub, "TaxAmount")
        cat_id = _text(sub, "TaxCategory/ID") or "?"
        pct = _text(sub, "TaxCategory/Percent") or "0"
        key = (cat_id, pct)
        if taxable is None or tax is None:
            err("BR-45", "TaxSubtotal", "taxable amount and tax amount are required")
            continue
        subtotal_sum += tax
        if per_category.pop(key, None) != taxable:
            err(
                "BR-S-08" if cat_id == "S" else "BR-K-08",
                f"TaxSubtotal {cat_id} {pct}",
                "does not equal its lines",
            )
        # Rounded per line, VAT may sit a cent per line away from base x rate; more is an error.
        n_lines = sum(
            1 for ln in lines if (_text(ln, "Item/ClassifiedTaxCategory/Percent") or "0") == pct
        )
        if cat_id == "S" and abs(r2(taxable * Decimal(pct) / 100) - tax) > CENT * max(1, n_lines):
            err("BR-S-09", f"TaxSubtotal S {pct}", "VAT is not the base times the rate")
        if cat_id == "K":
            if tax != 0:
                err("BR-K-09", "TaxSubtotal K", "intra-Community supply carries no VAT")
            if not _text(
                root, "AccountingSupplierParty/Party/PartyTaxScheme/CompanyID"
            ) or not _text(root, "AccountingCustomerParty/Party/PartyTaxScheme/CompanyID"):
                err(
                    "BR-K-02",
                    "PartyTaxScheme",
                    "both VAT ids are required for an intra-Community supply",
                )
    for (cat_id, pct), _ in per_category.items():
        err(
            "BR-CO-18", f"TaxSubtotal {cat_id} {pct}", "a VAT category of the lines has no subtotal"
        )
    if subtotal_sum != tax_amount:
        err("BR-CO-14", "TaxTotal/TaxAmount", "must be the sum of the subtotals")

    means = root.find(_p("PaymentMeans"))
    if means is not None and _text(means, "PaymentMeansCode") == "58":
        iban = _text(means, "PayeeFinancialAccount/ID")
        if not iban:
            err("BR-61", "PayeeFinancialAccount", "a credit transfer needs the account")
        elif not _iban_ok(iban):
            err("IBAN", "PayeeFinancialAccount", "the IBAN check digits are wrong")
    return kind, errors
