"""How each billing system prints numbers. Ground truth stores these exact strings."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from claimpilot_datagen.invoices.model import Layout


def number(x: Decimal, decimals: int, thousands: str) -> str:
    q = x.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    whole, _, frac = f"{abs(q):f}".partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    body = thousands.join(groups)
    return f"{sign}{body},{frac}" if decimals else f"{sign}{body}"


@dataclass(frozen=True)
class Style:
    thousands: str
    qty_decimals: int
    unit_decimals: int
    recap_decimals: int  # WHOLESALE prints the VAT recap with 4 decimals
    date_format: str

    def qty(self, x: Decimal) -> str:
        return number(x, self.qty_decimals, self.thousands)

    def unit(self, x: Decimal) -> str:
        return number(x, self.unit_decimals, self.thousands)

    def amount(self, x: Decimal) -> str:
        return number(x, 2, self.thousands)

    def recap(self, x: Decimal) -> str:
        return number(x, self.recap_decimals, self.thousands)

    def gross_unit(self, x: Decimal) -> str:
        return number(x, 4, self.thousands)

    def pct(self, x: Decimal) -> str:
        return number(x, 2, "") + "%"

    def date(self, d: date) -> str:
        return d.strftime(self.date_format)


STYLES = {
    Layout.WHOLESALE: Style(".", 2, 2, 4, "%d.%m.%Y"),
    Layout.SAP: Style(".", 0, 2, 2, "%d.%m.%Y"),
    Layout.TANGRAM: Style(" ", 3, 3, 2, "%d.%m.%Y"),
    Layout.POHODA: Style(" ", 0, 2, 2, "%d.%m.%Y"),
    Layout.SCAN_EN: Style(" ", 0, 2, 2, "%d.%m.%Y"),
}
