"""Reference arithmetic of an invoice, per layout. This is the generator's own calculation; the
validation code in the worker is written separately, so one bug cannot hide in both."""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from claimpilot_datagen.invoices.model import Invoice, Layout, VatMethod, VatRow

CENT = Decimal("0.01")
Q4 = Decimal("0.0001")
HUNDRED = Decimal(100)

VAT_METHOD = {
    Layout.WHOLESALE: VatMethod.PER_RATE,
    Layout.SAP: VatMethod.PER_RATE,
    Layout.TANGRAM: VatMethod.PER_RATE,
    Layout.POHODA: VatMethod.PER_LINE,
    Layout.SCAN_EN: VatMethod.PER_RATE,
}


def r2(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _pct(p: Decimal) -> Decimal:
    return 1 - p / HUNDRED


def compute(inv: Invoice) -> Invoice:
    inv.vat_method = VAT_METHOD[inv.layout]
    bases: dict[int, Decimal] = defaultdict(Decimal)
    line_vat: dict[int, Decimal] = defaultdict(Decimal)
    for ln in inv.lines:
        ln.vat_rate = 0 if inv.reverse_charge else ln.product.vat_rate
        rate = Decimal(ln.vat_rate) / HUNDRED
        if inv.layout is Layout.SAP:
            ln.net_unit_price = r2(
                ln.unit_price * _pct(ln.struct_disc_pct) * _pct(ln.promo_disc_pct)
            )
            ln.line_net = r2(ln.qty * ln.net_unit_price)
        elif inv.layout is Layout.POHODA:
            ln.net_unit_price = ln.unit_price
            ln.line_net = r2(ln.qty * ln.unit_price * _pct(ln.discount_pct))
        else:
            ln.net_unit_price = ln.unit_price
            ln.line_net = r2(ln.qty * ln.unit_price)
        ln.gross_unit_price = (ln.net_unit_price * (1 + rate)).quantize(Q4, rounding=ROUND_HALF_UP)
        if inv.vat_method is VatMethod.PER_LINE:
            ln.vat_amount = r2(ln.line_net * rate)
            ln.line_gross = ln.line_net + ln.vat_amount
            line_vat[ln.vat_rate] += ln.vat_amount
        bases[ln.vat_rate] += ln.line_net
    for fee in inv.fees:
        if fee.included:
            continue
        rate = 0 if inv.reverse_charge else fee.vat_rate
        bases[rate] += fee.net
        if inv.vat_method is VatMethod.PER_LINE:
            line_vat[rate] += r2(fee.net * Decimal(rate) / HUNDRED)
    inv.recap = []
    for rate in sorted(bases):
        vat = (
            line_vat[rate]
            if inv.vat_method is VatMethod.PER_LINE
            else r2(bases[rate] * Decimal(rate) / HUNDRED)
        )
        inv.recap.append(VatRow(rate, bases[rate], vat))
    inv.total_net = sum((r.base for r in inv.recap), Decimal(0))
    inv.total_vat = sum((r.vat for r in inv.recap), Decimal(0))
    inv.total = inv.total_net + inv.total_vat
    inv.amount_due = inv.total - inv.proforma_settled
    return inv
