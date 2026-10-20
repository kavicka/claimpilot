"""Match an invoice against the ERP: who sent it, where the money goes, what was ordered and
what arrived and what earlier invoices already took of it. Each difference is a named finding;
nothing here calls a model.

Order of work: the supplier by VAT id, then by IČO (none found ends matching: an unknown
supplier is for a person to look at); the IBAN against the supplier's record; for a credit note,
its original; then the order by the printed number, each invoice line to an order line by EAN,
else by the supplier's code, and the quantity against the goods receipt. The price compared is
the line total over the quantity, so discounts and rounding are already in it.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from claimpilot_core.invoice_values import parse_number
from claimpilot_core.trade_ids import normalize_gtin

HUNDRED = Decimal(100)


class ErpView(Protocol):
    def supplier(self, ico: str | None, vat_id: str | None) -> dict[str, Any] | None: ...
    def order(self, number: str) -> dict[str, Any] | None: ...
    def receipts_for(self, number: str) -> list[dict[str, Any]]: ...
    def invoice_known(self, supplier_ico: str, number: str) -> bool: ...
    def invoiced_before(self, number: str) -> dict[int, Decimal]:
        """Per order line (index), the quantity on earlier invoices of this supplier and order
        that still stand (not rejected, not failed)."""
        ...


@dataclass(frozen=True)
class MatchSettings:
    price_tolerance_pct: Decimal = Decimal("0.5")
    per_supplier: dict[str, Decimal] = field(default_factory=dict)  # IČO -> tolerance %

    def tolerance_for(self, ico: str | None) -> Decimal:
        return self.per_supplier.get(ico or "", self.price_tolerance_pct)


@dataclass
class Finding:
    kind: str  # unknown_supplier | iban_changed | unknown_order | not_ordered | price_diff | ...
    line: int | None = None  # 0-based index of the invoice line
    detail: str = ""


@dataclass
class LineMatch:
    line: int
    order_line: int | None
    received: Decimal | None = None
    quantity: Decimal | None = None  # what this invoice bills, kept for the invoices after it
    invoiced_before: Decimal = Decimal(0)  # what earlier invoices billed of the same order line


@dataclass
class MatchResult:
    supplier: dict[str, Any] | None = None
    order: dict[str, Any] | None = None
    findings: list[Finding] = field(default_factory=list)
    lines: list[LineMatch] = field(default_factory=list)

    @property
    def needs_info(self) -> bool:
        return any(f.kind == "unknown_original" for f in self.findings)


def _compact(value: str | None) -> str:
    return (value or "").replace(" ", "").upper()


def _gtin14(value: str | None) -> str | None:
    if not value:
        return None
    g = normalize_gtin(value).gtin
    return g.zfill(14) if g else None


def _key(line: dict[str, Any]) -> tuple[str | None, str | None]:
    return _gtin14(line.get("ean")), (line.get("supplier_code") or "").strip() or None


def _pick(line: dict[str, Any], candidates: list[dict[str, Any]], used: set[int]) -> int | None:
    """The first unused candidate with the same EAN, else with the same supplier code."""
    ean, code = _key(line)
    for want, pos in ((ean, 0), (code, 1)):
        if want is None:
            continue
        for i, c in enumerate(candidates):
            if i not in used and _key(c)[pos] == want:
                return i
    return None


def match(
    header: dict[str, str],
    lines: list[dict[str, str]],
    erp: ErpView,
    settings: MatchSettings,
    *,
    kind: str = "invoice",
) -> MatchResult:
    result = MatchResult()
    ico = re.sub(r"\D", "", header.get("supplier_ico") or "") or None
    supplier = erp.supplier(ico, _compact(header.get("supplier_vat_id")) or None)
    if supplier is None:
        result.findings.append(Finding("unknown_supplier"))
        return result
    result.supplier = supplier
    ico = supplier["ico"]
    if header.get("supplier_iban") and _compact(header["supplier_iban"]) != _compact(
        supplier["iban"]
    ):
        result.findings.append(Finding("iban_changed", detail="IBAN not on the supplier's record"))
    if kind == "credit_note":
        original = header.get("original_invoice_number")
        if not original or not erp.invoice_known(ico, original):
            result.findings.append(Finding("unknown_original", detail=original or ""))
        return result
    number = header.get("order_number")
    order = erp.order(number) if number else None
    if order is None:
        result.findings.append(Finding("unknown_order", detail=number or "no order number"))
        return result
    buyer = re.sub(r"\D", "", header.get("buyer_ico") or "")
    if order.get("supplier_ico") != ico or (
        buyer and order.get("buyer_ico") and order["buyer_ico"] != buyer
    ):
        # Another party's order: its lines and receipts say nothing about this invoice.
        detail = (
            f"order {order['number']} of {order.get('supplier_ico')} for {order.get('buyer_ico')}"
        )
        result.findings.append(Finding("order_mismatch", detail=detail))
        return result
    result.order = order
    receipt_lines = [rl for r in erp.receipts_for(order["number"]) for rl in r["lines"]]
    tolerance = settings.tolerance_for(ico)
    used_order: set[int] = set()
    used_receipt: set[int] = set()
    # A receipt can be invoiced once: what earlier invoices took is not left for this one.
    billed = erp.invoiced_before(order["number"]) if kind != "proforma" else {}
    for i, line in enumerate(lines):
        j = _pick(line, order["lines"], used_order)
        lm = LineMatch(i, j)
        result.lines.append(lm)
        lm.quantity = parse_number(line.get("quantity"))
        if j is None:
            result.findings.append(Finding("not_ordered", i))
            continue
        used_order.add(j)
        ordered = order["lines"][j]
        qty, net = parse_number(line.get("quantity")), parse_number(line.get("line_net"))
        price = Decimal(str(ordered["unit_price"]))
        if qty and net is not None and price:
            diff_pct = abs(net / qty - price) / price * HUNDRED
            if diff_pct > tolerance:
                result.findings.append(
                    Finding("price_diff", i, f"{net / qty:.4f} invoiced, {price} ordered")
                )
        if kind == "proforma":
            continue  # an advance comes before the delivery
        k = _pick(line, receipt_lines, used_receipt)
        if k is None:
            result.findings.append(Finding("not_received", i))
            continue
        used_receipt.add(k)
        lm.received = Decimal(str(receipt_lines[k]["qty"]))
        lm.invoiced_before = before = billed.get(j, Decimal(0))
        left = max(lm.received - before, Decimal(0))
        if qty is not None and left != qty:
            if qty < left:
                finding = Finding("over_delivery", i, f"{lm.received} received")
            elif before > 0:
                finding = Finding(
                    "already_invoiced", i, f"{lm.received} received, {before} on earlier invoices"
                )
            else:
                finding = Finding("short_delivery", i, f"{lm.received} received")
            result.findings.append(finding)
    return result
