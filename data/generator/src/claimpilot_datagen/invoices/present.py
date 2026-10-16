"""What an invoice prints, field by field: the template view and the ground truth come from the
same strings, so ground truth is exactly what is on the page.

Ground truth fields are `{"printed": ..., "value": ...}`: the text as printed and its normalized
value (Decimal as string, ISO date, compact IBAN, GTIN). A field is present only when the layout
prints it.
"""

from decimal import Decimal
from typing import Any

from claimpilot_core.trade_ids import normalize_gtin
from claimpilot_datagen.invoices.fmt import STYLES, Style
from claimpilot_datagen.invoices.model import DocKind, Invoice, Layout, Line

TITLES = {
    Layout.WHOLESALE: {
        DocKind.INVOICE: "FAKTÚRA",
        DocKind.CREDIT_NOTE: "DOBROPIS",
        DocKind.PROFORMA: "ZÁLOHOVÁ FAKTÚRA",
    },
    Layout.SAP: {
        DocKind.INVOICE: "Faktúra",
        DocKind.CREDIT_NOTE: "Opravná faktúra",
        DocKind.PROFORMA: "Zálohová faktúra",
    },
    Layout.TANGRAM: {
        DocKind.INVOICE: "Daňový doklad - FAKTÚRA (FV)",
        DocKind.CREDIT_NOTE: "Opravný daňový doklad - DOBROPIS",
        DocKind.PROFORMA: "Zálohová faktúra (ZF) - nie je daňový doklad",
    },
    Layout.POHODA: {
        DocKind.INVOICE: "FAKTÚRA",
        DocKind.CREDIT_NOTE: "OPRAVNÁ FAKTÚRA - DOBROPIS",
        DocKind.PROFORMA: "ZÁLOHOVÁ FAKTÚRA",
    },
    Layout.SCAN_EN: {
        DocKind.INVOICE: "Invoice",
        DocKind.CREDIT_NOTE: "Credit note",
        DocKind.PROFORMA: "Proforma invoice",
    },
}
UNIT = {
    Layout.WHOLESALE: "KS",
    Layout.SAP: "",
    Layout.TANGRAM: "ks",
    Layout.POHODA: "ks",
    Layout.SCAN_EN: "",
}
LINE_RATE = {
    Layout.WHOLESALE: "{r}",
    Layout.SAP: "{r}",
    Layout.TANGRAM: "{r}%",
    Layout.POHODA: "{r}%",
    Layout.SCAN_EN: "{r}",
}
RECAP_RATE = {
    Layout.WHOLESALE: "{r}%",
    Layout.SAP: "{r}",
    Layout.TANGRAM: "{r},00%",
    Layout.POHODA: "{r}%",
    Layout.SCAN_EN: "{r}",
}
REVERSE_CHARGE_NOTE = {
    Layout.SAP: "Dodanie tovaru oslobodené od dane podľa § 43 zákona o DPH - Intra-Community "
    "supply, Art. 138, VAT Directive 2006/112/EC.",
    Layout.SCAN_EN: "Intra-Community supply: the place of performance is outside the supplier's "
    "territory. The recipient accounts for the VAT (reverse charge, Art. 196, VAT Directive "
    "2006/112/EC).",
}


def f(printed: str, value: Any) -> dict[str, Any]:
    return {
        "printed": printed,
        "value": value if value is None or isinstance(value, bool) else str(value),
    }


def _iban(iban: str) -> dict[str, Any]:
    return f(iban, iban.replace(" ", ""))


def _gtin(printed: str | None) -> dict[str, Any] | None:
    if printed is None:
        return None
    return f(printed, normalize_gtin(printed).gtin)


def line_view(inv: Invoice, ln: Line, st: Style) -> dict[str, Any]:
    layout = inv.layout
    cells: dict[str, Any] = {
        "name": f(
            ln.product.name.upper() if layout is Layout.TANGRAM else ln.product.name,
            ln.product.name,
        ),
        "quantity": f(st.qty(ln.qty), ln.qty),
        "line_net": f(st.amount(ln.line_net), ln.line_net),
    }
    if layout is not Layout.SCAN_EN:  # the English scan layout prints no VAT column
        cells["vat_rate"] = f(LINE_RATE[layout].format(r=ln.vat_rate), ln.vat_rate)
    if UNIT[layout]:
        cells["unit"] = f(UNIT[layout], UNIT[layout].lower())
    if ln.printed_ean is not None:
        cells["ean"] = _gtin(ln.printed_ean)
    if layout in (Layout.SAP, Layout.TANGRAM, Layout.POHODA):
        cells["supplier_code"] = f(ln.product.supplier_code, ln.product.supplier_code)
    cells["unit_price"] = f(st.unit(ln.unit_price), ln.unit_price)
    if layout is Layout.POHODA:
        cells["discount_pct"] = f(st.pct(ln.discount_pct), ln.discount_pct)
        cells["vat_amount"] = f(st.amount(ln.vat_amount or Decimal(0)), ln.vat_amount)
        cells["line_gross"] = f(st.amount(ln.line_gross or Decimal(0)), ln.line_gross)
    if layout is Layout.SAP:
        if ln.struct_disc_pct:
            cells["struct_discount_pct"] = f(st.pct(ln.struct_disc_pct), ln.struct_disc_pct)
        if ln.promo_disc_pct:
            cells["promo_discount_pct"] = f(st.pct(ln.promo_disc_pct), ln.promo_disc_pct)
        cells["net_unit_price"] = f(st.unit(ln.net_unit_price), ln.net_unit_price)
    if layout is Layout.TANGRAM:
        cells["gross_unit_price"] = f(st.gross_unit(ln.gross_unit_price), ln.gross_unit_price)
    if layout is Layout.WHOLESALE and ln.product.sukl:
        cells["sukl_code"] = f(ln.product.sukl, ln.product.sukl)
    if layout is Layout.SCAN_EN:
        cells["origin"] = f(ln.product.origin, ln.product.origin)
        if ln.product.customs:
            cells["customs_code"] = f(ln.product.customs, ln.product.customs)
    batches = [
        {
            "batch": f(b.batch, b.batch),
            "expiry": f(b.expiry, b.expiry),
            "quantity": f(st.qty(b.qty), b.qty),
        }
        for b in ln.batches
    ]
    return {"cells": cells, "batches": batches, "page": ln.page}


def _symbols(inv: Invoice) -> dict[str, Any]:
    out = {"variable_symbol": f(inv.variable_symbol, inv.variable_symbol)}
    if inv.layout in (Layout.SAP, Layout.TANGRAM, Layout.POHODA):
        out["constant_symbol"] = f(inv.constant_symbol, inv.constant_symbol)
    if inv.specific_symbol:
        out["specific_symbol"] = f(inv.specific_symbol, inv.specific_symbol)
    return out


def header_view(inv: Invoice) -> dict[str, Any]:
    st = STYLES[inv.layout]
    s, b = inv.supplier, inv.buyer
    h: dict[str, Any] = {
        "document_kind": f(TITLES[inv.layout][inv.kind], inv.kind.value),
        "invoice_number": f(inv.number, inv.number),
        "issue_date": f(st.date(inv.issue_date), inv.issue_date.isoformat()),
        "supplier_name": f(s.name, s.name),
        "supplier_ico": f(s.ico, s.ico),
        "supplier_vat_id": f(s.vat_id, s.vat_id),
        "supplier_iban": _iban(inv.iban),
        "buyer_name": f(b.name, b.name),
        "buyer_vat_id": f(b.vat_id, b.vat_id),
        "currency": f("EUR", "EUR"),
        "total": f(st.amount(inv.total), inv.total),
    }
    if inv.layout is not Layout.SCAN_EN:
        h |= {
            "tax_point_date": f(st.date(inv.tax_date), inv.tax_date.isoformat()),
            "due_date": f(st.date(inv.due_date), inv.due_date.isoformat()),
            "supplier_dic": f(s.dic, s.dic),
            "buyer_ico": f(b.ico, b.ico),
            "buyer_dic": f(b.dic, b.dic),
            **_symbols(inv),
        }
    h["amount_due"] = f(st.amount(inv.amount_due), inv.amount_due)
    if inv.layout is Layout.WHOLESALE:
        h["total"] = f(st.recap(inv.total), inv.total)  # "Spolu" with 4 decimals
    elif inv.layout is not Layout.SCAN_EN:
        h["total_net"] = f(st.amount(inv.total_net), inv.total_net)
        h["total_vat"] = f(st.amount(inv.total_vat), inv.total_vat)
    if inv.order_number:
        h["order_number"] = f(inv.order_number, inv.order_number)
    if inv.delivery_notes:
        joined = ", ".join(inv.delivery_notes)
        h["delivery_note_numbers"] = f(joined, joined)
    if inv.customer_number and inv.layout in (Layout.WHOLESALE, Layout.SAP):
        h["customer_number"] = f(inv.customer_number, inv.customer_number)
    if inv.original_number:
        h["original_invoice_number"] = f(inv.original_number, inv.original_number)
    if inv.proforma_number:
        h["proforma_number"] = f(inv.proforma_number, inv.proforma_number)
        h["proforma_settled"] = f(st.amount(-inv.proforma_settled), -inv.proforma_settled)
    if inv.reverse_charge:
        h["reverse_charge"] = f(REVERSE_CHARGE_NOTE[inv.layout], True)
    if inv.second_currency and inv.fx_rate:
        total2 = (inv.total * inv.fx_rate).quantize(Decimal("0.01"))
        h["second_currency_total"] = f(st.amount(total2), total2)
        h["fx_rate"] = f(st.unit(inv.fx_rate), inv.fx_rate)
    return h


def recap_view(inv: Invoice) -> list[dict[str, Any]]:
    st = STYLES[inv.layout]
    return [
        {
            "rate": f(RECAP_RATE[inv.layout].format(r=r.rate), r.rate),
            "base": f(st.recap(r.base), r.base),
            "vat": f(st.recap(r.vat), r.vat),
        }
        for r in inv.recap
    ]


def fees_view(inv: Invoice) -> list[dict[str, Any]]:
    st = STYLES[inv.layout]
    return [
        {
            "kind": fee.kind,
            "label": f(fee.label, fee.label),
            "net": f(st.amount(fee.net), fee.net),
            "included": fee.included,
        }
        for fee in inv.fees
    ]


def view(inv: Invoice) -> dict[str, Any]:
    """Everything a template needs; `header`, `lines`, `recap`, `fees` are also ground truth."""
    st = STYLES[inv.layout]
    return {
        "inv": inv,
        "st": st,
        "title": TITLES[inv.layout][inv.kind],
        "header": header_view(inv),
        "lines": [line_view(inv, ln, st) for ln in inv.lines],
        "recap": recap_view(inv),
        "fees": fees_view(inv),
    }
