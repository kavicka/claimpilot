"""Synthetic supplier invoices: parties, products, lines and the ERP records they match against.

Amounts are Decimal and computed by `calc`; the printed form of every value comes from the
layout's formatter (`fmt`), so ground truth holds exactly what the page shows.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum


class Layout(StrEnum):
    """Five billing systems common in Slovakia and Czechia (layouts only; names are fictional)."""

    WHOLESALE = "wholesale"  # multi-page wholesaler list: batch, expiry, EAN under the name
    SAP = "sap"  # tariff, structural and promo discount, dual currency, terms page
    TANGRAM = "tangram"  # supplier codes without EAN, 3-decimal unit prices, recap at the top
    POHODA = "pohoda"  # per-line discount, VAT per line, multi-line names, transport fee
    SCAN_EN = "scan_en"  # English intra-EU invoice, batches, reverse charge, scanned with a stamp


class DocKind(StrEnum):
    INVOICE = "invoice"
    CREDIT_NOTE = "credit_note"
    PROFORMA = "proforma"


class VatMethod(StrEnum):
    PER_RATE = "per_rate"  # VAT = round(base of the rate x rate)
    PER_LINE = "per_line"  # VAT rounded on each line, the recap sums the lines


@dataclass
class Party:
    key: str
    name: str
    street: str
    zip: str
    city: str
    country: str  # SK | CZ
    ico: str
    dic: str
    vat_id: str
    iban: str
    bank: str
    swift: str
    email: str
    phone: str
    contact: str  # fictional person issuing the invoice
    register: str  # commercial register line


@dataclass
class Product:
    ean: str | None
    supplier_code: str
    name: str
    vat_rate: int  # 5 | 19 | 23 (Slovak rates from 2025)
    list_price: Decimal  # net, per unit
    sukl: str | None = None  # medicines only
    origin: str = "SK"
    customs: str | None = None


@dataclass
class Batch:
    batch: str
    expiry: str  # MM/YY as printed
    qty: Decimal


@dataclass
class Line:
    product: Product
    qty: Decimal
    unit_price: Decimal  # net per unit before discounts, as the layout prints it
    discount_pct: Decimal = Decimal(0)  # POHODA
    struct_disc_pct: Decimal = Decimal(0)  # SAP
    promo_disc_pct: Decimal = Decimal(0)  # SAP
    printed_ean: str | None = None  # None: the layout prints no EAN for this line
    batches: list[Batch] = field(default_factory=list)
    # computed by calc
    vat_rate: int = 0  # 0 under reverse charge
    net_unit_price: Decimal = Decimal(0)
    gross_unit_price: Decimal = Decimal(0)  # TANGRAM prints it to 4 decimals
    line_net: Decimal = Decimal(0)
    vat_amount: Decimal | None = None
    line_gross: Decimal | None = None
    page: int | None = None  # where it is printed (after rendering)


@dataclass
class Fee:
    kind: str  # transport | recycling
    label: str
    net: Decimal
    vat_rate: int
    included: bool  # True: already inside the line prices, printed for information only


@dataclass
class VatRow:
    rate: int
    base: Decimal
    vat: Decimal


@dataclass
class Invoice:
    invoice_id: str
    split: str
    layout: Layout
    kind: DocKind
    number: str
    supplier: Party
    buyer: Party
    delivery_point: str
    issue_date: date
    tax_date: date
    due_date: date
    lines: list[Line]
    order_number: str | None = None
    delivery_notes: list[str] = field(default_factory=list)
    customer_number: str | None = None
    constant_symbol: str = "0008"
    specific_symbol: str | None = None
    currency: str = "EUR"
    second_currency: str | None = None  # CZK on SAP invoices from the Czech supplier
    fx_rate: Decimal | None = None  # units of second currency per EUR, as printed
    fees: list[Fee] = field(default_factory=list)
    reverse_charge: bool = False
    original_number: str | None = None  # credit note: the invoice it corrects
    proforma_number: str | None = None  # invoice that settles an advance
    proforma_settled: Decimal = Decimal(0)
    printed_iban: str | None = None  # None: the supplier's IBAN on record
    edge_cases: set[str] = field(default_factory=set)
    duplicate_of: str | None = None  # same file sent again
    # computed by calc
    vat_method: VatMethod = VatMethod.PER_RATE
    recap: list[VatRow] = field(default_factory=list)
    total_net: Decimal = Decimal(0)
    total_vat: Decimal = Decimal(0)
    total: Decimal = Decimal(0)
    amount_due: Decimal = Decimal(0)
    # set after rendering
    pages_total: int = 1
    pages_present: int = 1

    @property
    def variable_symbol(self) -> str:
        return "".join(c for c in self.number if c.isdigit())

    @property
    def iban(self) -> str:
        return self.printed_iban or self.supplier.iban


@dataclass
class OrderLine:
    ean: str | None
    supplier_code: str
    qty: Decimal
    unit_price: Decimal  # agreed net price after discounts


@dataclass
class PurchaseOrder:
    number: str
    supplier_ico: str
    buyer_ico: str
    delivery_point: str
    ordered_on: date
    lines: list[OrderLine]


@dataclass
class Receipt:
    delivery_note: str
    order_number: str
    received_on: date
    lines: list[OrderLine]  # qty = received


@dataclass
class Finding:
    """A discrepancy planted on purpose; validation and matching must find exactly these."""

    kind: str  # short_delivery | price_diff | iban_changed | unknown_supplier | duplicate | ...
    line: int | None = None
    detail: str = ""
