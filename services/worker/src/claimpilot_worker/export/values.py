"""From stored invoice values (as printed, corrected by the handler) to the UBL builder's input.
Everything is parsed here; a value that does not parse stops the export with its field name."""

import re
from decimal import Decimal
from typing import Any

from claimpilot_core.invoice_values import parse_number, parse_quantity, parse_vat_rate
from claimpilot_core.normalize import parse_date
from claimpilot_core.trade_ids import normalize_gtin
from claimpilot_worker.export.ubl import Line, Party, UblInvoice


class ExportError(ValueError):
    def __init__(self, field: str, value: str | None) -> None:
        super().__init__(f"{field}: cannot read {value!r}")
        self.field = field


def _need(values: dict[str, str], name: str) -> str:
    v = values.get(name)
    if not v:
        raise ExportError(name, v)
    return v


def _num(values: dict[str, str], name: str, ref: str) -> Decimal:
    n = parse_number(values.get(name))
    if n is None:
        raise ExportError(ref, values.get(name))
    return n


def _country(vat_id: str | None, default: str) -> str:
    return vat_id[:2].upper() if vat_id and vat_id[:2].isalpha() else default


def from_values(
    header: dict[str, str],
    lines: list[dict[str, str]],
    *,
    kind: str,
    supplier_record: dict[str, Any] | None,
    buyer_record: dict[str, Any] | None,
) -> UblInvoice:
    supplier_vat = (header.get("supplier_vat_id") or "").replace(" ", "").upper() or None
    buyer_vat = (header.get("buyer_vat_id") or "").replace(" ", "").upper() or None
    s, b = supplier_record or {}, buyer_record or {}
    issue = parse_date(_need(header, "issue_date"))
    if issue is None:
        raise ExportError("issue_date", header.get("issue_date"))
    out_lines = []
    for i, ln in enumerate(lines, start=1):
        qty, unit = parse_quantity(ln.get("quantity"))
        if qty is None:
            raise ExportError(f"lines[{i}].quantity", ln.get("quantity"))
        net = _num(ln, "line_net", f"lines[{i}].line_net")
        rate = parse_vat_rate(ln.get("vat_rate"))
        gtin = normalize_gtin(ln["ean"]).gtin if ln.get("ean") else None
        out_lines.append(
            Line(
                quantity=qty,
                unit=ln.get("unit") or unit or "ks",
                name=_need(ln, "name") if ln.get("name") else f"line {i}",
                net_price=(net / qty) if qty else net,
                line_net=net,
                vat_rate=rate if rate is not None else 0,
                gtin=gtin.zfill(14) if gtin else None,
                supplier_code=ln.get("supplier_code"),
            )
        )
    # The price per unit is the line total over the quantity, so that R120 (quantity x price,
    # rounded to cents = line amount) holds for every printed line; four decimals are enough.
    for ln in out_lines:
        ln.net_price = ln.net_price.quantize(Decimal("0.0001"))
        if (ln.quantity * ln.net_price).quantize(Decimal("0.01")) != ln.line_net:
            ln.net_price = (ln.line_net / ln.quantity).quantize(Decimal("0.000001"))
    printed_vat: dict[int, Decimal] = {}
    for i in range(20):
        rate = parse_vat_rate(header.get(f"recap[{i}].rate"))
        vat = parse_number(header.get(f"recap[{i}].vat"))
        if rate is not None and vat is not None:
            printed_vat[rate] = vat
    standard = max((ln.vat_rate for ln in out_lines), default=0)
    charges = []
    for i in range(10):
        net = parse_number(header.get(f"fees[{i}].net"))
        if net is not None:
            charges.append((header.get(f"fees[{i}].label") or "Fee", net, standard))
    return UblInvoice(
        kind=kind,
        charges=charges,
        printed_vat=printed_vat,
        number=_need(header, "invoice_number"),
        issue_date=issue,
        due_date=parse_date(header.get("due_date")),
        tax_point_date=parse_date(header.get("tax_point_date")),
        currency=(header.get("currency") or "EUR")[:3].upper(),
        supplier=Party(
            name=s.get("name") or _need(header, "supplier_name"),
            ico=re.sub(r"\D", "", header.get("supplier_ico") or "") or s.get("ico"),
            vat_id=supplier_vat or s.get("vat_id"),
            country=s.get("country") or _country(supplier_vat, "SK"),
            street=s.get("street"),
            city=s.get("city"),
            zip=s.get("zip"),
        ),
        buyer=Party(
            name=b.get("name") or _need(header, "buyer_name"),
            ico=re.sub(r"\D", "", header.get("buyer_ico") or "") or b.get("ico"),
            vat_id=buyer_vat or b.get("vat_id"),
            country=_country(buyer_vat, "SK"),
            street=b.get("street"),
            city=b.get("city"),
            zip=b.get("zip"),
        ),
        iban=header.get("supplier_iban"),
        payment_id=header.get("variable_symbol"),
        order_number=header.get("order_number"),
        delivery_note=(header.get("delivery_note_numbers") or "").split(",")[0].strip() or None,
        original_number=header.get("original_invoice_number"),
        reverse_charge=bool(header.get("reverse_charge")),
        lines=out_lines,
        prepaid=abs(parse_number(header.get("proforma_settled")) or Decimal(0)),
    )
