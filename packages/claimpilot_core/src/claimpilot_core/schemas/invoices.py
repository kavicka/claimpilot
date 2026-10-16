"""Field sets of supplier invoices, credit notes and proformas.

As for claims (ADR-002), every value is a string exactly as printed; code normalizes and checks
it. Field names match the invoice ground truth (data/synthetic/invoices), so the eval compares
them one to one. The descriptions go into the prompts, so they are written for the model.
"""

from typing import Literal

from pydantic import BaseModel, Field

Printed = str | None


class VatRecapRow(BaseModel):
    rate: Printed = Field(None, description="VAT rate of the row as printed, e.g. '19%' or '23'")
    base: Printed = Field(None, description="Tax base (základ) of that rate as printed")
    vat: Printed = Field(None, description="VAT amount (daň, DPH) of that rate as printed")


class Fee(BaseModel):
    label: Printed = Field(None, description="Fee text outside the item list, e.g. 'Doprava'")
    net: Printed = Field(None, description="Fee amount as printed")


class InvoiceHeader(BaseModel):
    """Everything on the invoice except the line items."""

    invoice_number: Printed = Field(None, description="Číslo faktúry / dobropisu / Invoice No.")
    issue_date: Printed = Field(None, description="Dátum vystavenia / vyhotovenia / Date of issue")
    tax_point_date: Printed = Field(
        None, description="Dátum dodania / daňová povinnosť (tax point), not the issue date"
    )
    due_date: Printed = Field(None, description="Dátum splatnosti / Splatnosť")
    variable_symbol: Printed = Field(None, description="Variabilný symbol")
    constant_symbol: Printed = Field(None, description="Konštantný symbol")
    specific_symbol: Printed = Field(None, description="Špecifický symbol")
    order_number: Printed = Field(None, description="The buyer's order number (objednávka)")
    delivery_note_numbers: Printed = Field(
        None, description="Delivery note numbers (dodací list), as printed, comma-separated"
    )
    customer_number: Printed = Field(
        None, description="Only a number labelled zákaznícke číslo / číslo zákazníka"
    )
    supplier_name: Printed = Field(None, description="Supplier (dodávateľ, seller) company name")
    supplier_ico: Printed = Field(None, description="Supplier IČO / IČ / ID")
    supplier_dic: Printed = Field(None, description="Supplier DIČ, after a DIČ label")
    supplier_vat_id: Printed = Field(None, description="Supplier IČ DPH / VAT ID with prefix")
    supplier_iban: Printed = Field(None, description="Supplier IBAN as printed")
    buyer_name: Printed = Field(None, description="Buyer (odberateľ) company name")
    buyer_ico: Printed = Field(None, description="Buyer IČO")
    buyer_dic: Printed = Field(None, description="Buyer DIČ, after a DIČ label")
    buyer_vat_id: Printed = Field(None, description="Buyer IČ DPH / VAT Reg.No.")
    currency: Printed = Field(None, description="Invoice currency code")
    total_net: Printed = Field(None, description="Total without VAT (základ spolu)")
    total_vat: Printed = Field(None, description="Total VAT (daň spolu)")
    total: Printed = Field(None, description="Total with VAT (spolu, celkom, Total)")
    amount_due: Printed = Field(
        None, description="Amount to pay (k úhrade, Total Due), after any advance is deducted"
    )
    original_invoice_number: Printed = Field(
        None, description="Credit notes: number of the invoice being corrected"
    )
    proforma_number: Printed = Field(None, description="Number of a settled advance (záloha)")
    proforma_settled: Printed = Field(None, description="Settled advance amount as printed")
    second_currency_total: Printed = Field(
        None, description="Total in a second currency (e.g. CZK), if printed"
    )
    fx_rate: Printed = Field(None, description="Exchange rate (kurz) as printed")
    reverse_charge: Printed = Field(
        None,
        description="The note on VAT exemption or reverse charge (intra-Community supply), "
        "copied as printed",
    )
    recap: list[VatRecapRow] = Field(
        default_factory=list, description="VAT recap: one row per printed rate"
    )
    fees: list[Fee] = Field(default_factory=list, description="Fees printed outside the items")


class Batch(BaseModel):
    batch: Printed = Field(None, description="Batch / lot / šarža code")
    expiry: Printed = Field(None, description="Expiry as printed, e.g. '01/27'")
    quantity: Printed = Field(None, description="Quantity of this batch, if printed per batch")


class InvoiceLine(BaseModel):
    item: int = Field(description="The item number given in the input, unchanged")
    supplier_code: Printed = Field(None, description="Supplier's product code (kód)")
    ean: Printed = Field(None, description="EAN / GTIN digits as printed, without the 'EAN' label")
    name: Printed = Field(None, description="Product name, all its wrapped lines joined by a space")
    quantity: Printed = Field(None, description="Quantity (množstvo, kusy) without the unit")
    unit: Printed = Field(None, description="Unit (MJ) as printed, e.g. 'KS', 'ks'")
    unit_price: Printed = Field(
        None, description="Unit price before discounts (J.cena, Tarifná cena, Cena/MJ, Unit price)"
    )
    discount_pct: Printed = Field(None, description="Discount percent of the line (zľava)")
    struct_discount_pct: Printed = Field(None, description="Štrukturálna zľava, if printed")
    promo_discount_pct: Printed = Field(None, description="Promo zľava, if printed")
    net_unit_price: Printed = Field(
        None, description="Unit price after discounts (Cena / ks bez DPH), if printed separately"
    )
    gross_unit_price: Printed = Field(None, description="Unit price with VAT, if printed")
    line_net: Printed = Field(
        None, description="Line total without VAT (Spolu bez DPH, Cena, Total, Total price)"
    )
    vat_rate: Printed = Field(None, description="VAT rate of the line as printed")
    vat_amount: Printed = Field(None, description="VAT amount of the line, if printed")
    line_gross: Printed = Field(None, description="Line total with VAT, if printed")
    sukl_code: Printed = Field(None, description="ŠUKL code (medicines), if printed")
    origin: Printed = Field(None, description="Country of origin, if printed")
    customs_code: Printed = Field(None, description="Customs tariff code, if printed")
    batches: list[Batch] = Field(default_factory=list, description="Batch rows of the item")


LINE_FIELDS = [k for k in InvoiceLine.model_fields if k not in ("item", "batches")]
BATCH_FIELDS = ["batch", "expiry", "batch_quantity"]
HEADER_FIELDS = [k for k in InvoiceHeader.model_fields if k not in ("recap", "fees")]

# The line call answers compactly: only the printed fields of an item, as (field, value) pairs.
# A full object per item, nulls included, ran past the output limit on a 20-item page.
LineField = Literal[
    "supplier_code", "ean", "name", "quantity", "unit", "unit_price", "discount_pct",
    "struct_discount_pct", "promo_discount_pct", "net_unit_price", "gross_unit_price",
    "line_net", "vat_rate", "vat_amount", "line_gross", "sukl_code", "origin", "customs_code",
    "batch", "expiry", "batch_quantity",
]  # fmt: skip


class CellValue(BaseModel):
    field: LineField
    value: str = Field(description="Exactly as printed")


class ItemValues(BaseModel):
    item: int = Field(description="The item number N from '#N', unchanged")
    values: list[CellValue] = Field(description="Only the fields printed for this item")


class InvoiceLines(BaseModel):
    items: list[ItemValues] = Field(default_factory=list, description="One entry per input item")


def line_guide() -> str:
    """Field names and what they hold, for the line prompt."""
    rows = [f"- {k}: {InvoiceLine.model_fields[k].description}" for k in LINE_FIELDS]
    rows += [
        f"- batch: {Batch.model_fields['batch'].description}",
        f"- expiry: {Batch.model_fields['expiry'].description}",
        "- batch_quantity: quantity printed on a batch row; give batch, expiry and "
        "batch_quantity of one batch row one after the other",
    ]
    return "\n".join(rows)
