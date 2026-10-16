"""Builds the invoice set: invoices, credit notes and proformas per split, the ERP records they
are matched against, and the discrepancies planted on purpose (with the finding each must raise).
"""

import random
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal

from claimpilot_core.trade_ids import gtin_check_digit
from claimpilot_datagen.invoices.calc import compute, r2
from claimpilot_datagen.invoices.model import (
    Batch,
    DocKind,
    Fee,
    Finding,
    Invoice,
    Layout,
    Line,
    OrderLine,
    Product,
    PurchaseOrder,
    Receipt,
)
from claimpilot_datagen.invoices.world import (
    DELIVERY_POINTS,
    World,
    build_world,
    make_iban,
    make_party,
)

SPLITS = {"train": 500, "dev": 60, "test": 60}
# Per 60 invoices; train scales them up. Each needs a layout that can carry it.
QUOTAS: dict[str, tuple[int, tuple[Layout, ...]]] = {
    "truncated": (2, (Layout.WHOLESALE,)),
    "duplicate_ean_lines": (3, (Layout.WHOLESALE,)),
    "ean_11_digits": (2, (Layout.WHOLESALE,)),
    "fee_outside_items": (3, (Layout.POHODA,)),
    "duplicated_page": (2, (Layout.TANGRAM,)),
    "credit_note": (4, (Layout.WHOLESALE, Layout.POHODA, Layout.SAP)),
    "credit_note_unknown_original": (1, (Layout.WHOLESALE, Layout.POHODA)),
    "proforma": (3, (Layout.TANGRAM, Layout.POHODA)),
    "short_delivery": (4, (Layout.WHOLESALE, Layout.TANGRAM, Layout.POHODA, Layout.SAP)),
    "price_diff": (4, (Layout.WHOLESALE, Layout.TANGRAM, Layout.POHODA, Layout.SAP)),
    "iban_changed": (3, tuple(Layout)),
    "unknown_supplier": (2, (Layout.TANGRAM, Layout.POHODA, Layout.WHOLESALE)),
    "duplicate_file": (2, tuple(Layout)),
}
LINES = {
    Layout.WHOLESALE: (8, 55),
    Layout.SAP: (1, 6),
    Layout.TANGRAM: (5, 18),
    Layout.POHODA: (5, 26),
    Layout.SCAN_EN: (1, 4),
}
PRICE_DIFF = Decimal("1.02")  # +2 %: above the ±0.5 % tolerance


@dataclass
class InvoiceSet:
    seed: int
    world: World
    invoices: list[Invoice] = field(default_factory=list)
    orders: list[PurchaseOrder] = field(default_factory=list)
    receipts: list[Receipt] = field(default_factory=list)
    findings: dict[str, list[Finding]] = field(default_factory=dict)
    unregistered_suppliers: set[str] = field(default_factory=set)


class InvoiceSampler:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.world = build_world(seed)
        self.out = InvoiceSet(seed, self.world)
        self._numbers: set[str] = set()

    # --- helpers ----------------------------------------------------------------------------

    def _number(self, rng: random.Random, layout: Layout, kind: DocKind) -> str:
        while True:
            n = {
                Layout.WHOLESALE: f"25{rng.randrange(10**7):07d}",
                Layout.SAP: f"29{rng.randrange(10**7):07d}",
                Layout.TANGRAM: f"2025{rng.randrange(10**5):05d}",
                Layout.POHODA: f"25{rng.randrange(10**7):07d}",
                Layout.SCAN_EN: f"25{rng.randrange(10**4):04d}",
            }[layout]
            if kind is DocKind.PROFORMA:
                n = f"ZF{n}"
            if n not in self._numbers:
                self._numbers.add(n)
                return n

    def _qty(self, rng: random.Random, layout: Layout) -> Decimal:
        match layout:
            case Layout.WHOLESALE:
                return Decimal(rng.choice([1, 2, 3, 5, 6, 10, 12, 20, 24, 30, 36, 40, 60, 90]))
            case Layout.SAP:
                return Decimal(rng.choice([12, 24, 36, 48, 60, 100, 144, 200]))
            case Layout.TANGRAM:
                return Decimal(rng.choice([5, 8, 10, 12, 15, 16, 20, 24, 30, 40]))
            case Layout.POHODA:
                return Decimal(rng.randrange(1, 11))
            case _:
                return Decimal(rng.choice([12, 24, 48, 96, 144, 200]))

    def _line(self, rng: random.Random, layout: Layout, product: Product) -> Line:
        ln = Line(product=product, qty=self._qty(rng, layout), unit_price=product.list_price)
        if layout is not Layout.TANGRAM:
            ln.printed_ean = product.ean
        if layout is Layout.POHODA:
            ln.discount_pct = Decimal(rng.choice([0, 0, 10, 15, 20]))
        if layout is Layout.SAP:
            ln.struct_disc_pct = Decimal(rng.choice([0, 0, 5, 8]))
            ln.promo_disc_pct = Decimal(rng.choice([0, 0, 0, 10]))
        if layout in (Layout.WHOLESALE, Layout.SCAN_EN) and product.vat_rate != 23:
            month = rng.randrange(1, 13)
            expiry = f"{month:02d}/{rng.randrange(26, 30)}"
            batch = f"{rng.randrange(1, 9)}{rng.choice('ABCEKLN')}{rng.randrange(10000, 99999)}"
            ln.batches = [Batch(batch, expiry, ln.qty)]
            if layout is Layout.SCAN_EN and rng.random() < 0.5 and ln.qty > 10:
                first = (ln.qty * Decimal(rng.choice(["0.9", "0.95", "0.97"]))).to_integral_value()
                other = f"{batch[:-3]}{rng.randrange(100, 999)}"
                ln.batches = [Batch(batch, expiry, first), Batch(other, expiry, ln.qty - first)]
        return ln

    def _dates(self, rng: random.Random) -> tuple[date, date, date]:
        issue = date(2025, 1, 2) + timedelta(days=rng.randrange(0, 290))
        tax = issue - timedelta(days=rng.choice([0, 0, 0, 1, 2]))
        due = issue + timedelta(days=rng.choice([14, 30, 30, 30, 60]))
        return issue, tax, due

    # --- one document -----------------------------------------------------------------------

    def _invoice(
        self, rng: random.Random, split: str, idx: int, supplier_key: str, cases: set[str]
    ) -> Invoice:
        w = self.world
        layout = w.layout_of[supplier_key]
        supplier = w.suppliers[supplier_key]
        if "unknown_supplier" in cases:
            from faker import Faker

            fk = Faker("sk_SK")
            fk.seed_instance(rng.randrange(2**31))
            name = rng.choice(["Pharmaline", "Medicorp", "Zdravo", "Naturis"]) + " Trade s.r.o."
            supplier = make_party(rng, fk, f"new-{split}-{idx}", name, "SK")
            self.out.unregistered_suppliers.add(supplier.key)
        products = list(w.catalogue[supplier_key])
        lo, hi = LINES[layout]
        n = rng.randrange(lo, hi + 1)
        if "truncated" in cases:
            n = max(n, 34)  # at least two pages, so the first one alone is incomplete
        chosen = rng.sample(products, min(n, len(products)))
        lines = [self._line(rng, layout, p) for p in chosen]
        if "duplicate_ean_lines" in cases:
            src = rng.choice(lines)
            twin = replace(src, qty=self._qty(rng, layout), batches=list(src.batches))
            lines.insert(lines.index(src) + 1, twin)
        if "ean_11_digits" in cases:
            body = "00" + "".join(str(rng.randrange(10)) for _ in range(10))
            ean = body + str(gtin_check_digit(body))  # GTIN-13 of a UPC-A code
            ln = rng.choice(lines)
            ln.product = replace(ln.product, ean=ean)
            ln.printed_ean = ean[2:]  # printed as 11 digits, its leading zero dropped
        kind = DocKind.INVOICE
        if "credit_note" in cases or "credit_note_unknown_original" in cases:
            kind = DocKind.CREDIT_NOTE
            lines = lines[: rng.randrange(1, min(3, len(lines)) + 1)]
            for ln in lines:
                ln.qty = -min(ln.qty, Decimal(rng.randrange(1, 6)))
                for b in ln.batches:
                    b.qty = ln.qty
        elif "proforma" in cases:
            kind = DocKind.PROFORMA
        issue, tax, due = self._dates(rng)
        inv = Invoice(
            invoice_id=f"{split[:2].upper()}-{idx:04d}",
            split=split,
            layout=layout,
            kind=kind,
            number=self._number(rng, layout, kind),
            supplier=supplier,
            buyer=w.buyers["retail" if rng.random() < 0.25 else "central"],
            delivery_point=rng.choice(DELIVERY_POINTS),
            issue_date=issue,
            tax_date=tax,
            due_date=due,
            lines=lines,
            customer_number=str(rng.randrange(1000, 99999)),
            specific_symbol=str(rng.randrange(100000, 999999)) if layout is Layout.SAP else None,
            reverse_charge=supplier.country != "SK",
            edge_cases=set(cases),
        )
        if layout is Layout.SAP:
            inv.second_currency, inv.fx_rate = (
                "CZK",
                Decimal(rng.choice(["24.92", "25.05", "24.71"])),
            )
        if layout is Layout.WHOLESALE and rng.random() < 0.3:
            inv.fees.append(
                Fee(
                    "recycling",
                    "Recyklačný poplatok",
                    Decimal(f"{rng.uniform(1, 6):.2f}"),
                    23,
                    True,
                )
            )
            inv.edge_cases.add("fee_included")
        if "fee_outside_items" in cases:
            inv.fees.append(
                Fee(
                    "transport", "Doprava", Decimal(rng.choice(["4.90", "6.50", "9.90"])), 23, False
                )
            )
        if kind is not DocKind.CREDIT_NOTE:
            inv.order_number = f"OB25{rng.randrange(10**6):06d}"
            if layout in (Layout.WHOLESALE, Layout.TANGRAM, Layout.SAP):
                prefix = {Layout.WHOLESALE: "T 25", Layout.TANGRAM: "DL/", Layout.SAP: "29"}[layout]
                inv.delivery_notes = [f"{prefix}{rng.randrange(10**4, 10**6)}"]
        inv.edge_cases |= {
            Layout.TANGRAM: {"missing_ean"},
            Layout.SAP: {"dual_currency", "terms_page", "reverse_charge"},
            Layout.SCAN_EN: {"scan", "reverse_charge", "stamp"},
            Layout.POHODA: {"multiline_names"},
            Layout.WHOLESALE: set(),
        }[layout]
        if any(len(ln.batches) > 1 for ln in lines):
            inv.edge_cases.add("batch_split")
        return compute(inv)

    # --- ERP records and planted discrepancies ------------------------------------------------

    def _erp(self, rng: random.Random, inv: Invoice) -> list[Finding]:
        findings: list[Finding] = []
        if inv.kind is DocKind.CREDIT_NOTE or inv.order_number is None:
            return findings
        if inv.supplier.key in self.out.unregistered_suppliers:
            inv.edge_cases -= {
                "price_diff",
                "short_delivery",
            }  # no order with a supplier not on record
            return findings
        order_lines = [
            OrderLine(
                ln.product.ean, ln.product.supplier_code, ln.qty, agreed_price(inv.layout, ln)
            )
            for ln in inv.lines
        ]
        received = [replace(o) for o in order_lines]
        if "price_diff" in inv.edge_cases:
            i = rng.randrange(len(inv.lines))
            ln = inv.lines[i]
            ln.unit_price = (
                r2(ln.unit_price * PRICE_DIFF)
                if inv.layout is not Layout.TANGRAM
                else (ln.unit_price * PRICE_DIFF).quantize(Decimal("0.001"))
            )
            compute(inv)
            findings.append(Finding("price_diff", i, f"{order_lines[i].unit_price} ordered"))
        if inv.kind is DocKind.PROFORMA:
            inv.edge_cases.discard("short_delivery")  # an advance comes before any receipt
        if "short_delivery" in inv.edge_cases:
            i = max(range(len(inv.lines)), key=lambda k: inv.lines[k].qty)
            short = max(Decimal(1), (inv.lines[i].qty / 4).to_integral_value())
            received[i].qty = inv.lines[i].qty - short
            findings.append(Finding("short_delivery", i, f"{received[i].qty} received"))
        self.out.orders.append(
            PurchaseOrder(
                inv.order_number,
                inv.supplier.ico,
                inv.buyer.ico,
                inv.delivery_point,
                inv.issue_date - timedelta(days=rng.randrange(2, 10)),
                order_lines,
            )
        )
        if inv.kind is DocKind.INVOICE:
            for note in inv.delivery_notes or [f"PR-{inv.order_number}"]:
                self.out.receipts.append(Receipt(note, inv.order_number, inv.tax_date, received))
        return findings

    # --- the whole set ------------------------------------------------------------------------

    def _plan(self, rng: random.Random, n: int) -> list[tuple[str, set[str]]]:
        keys = list(self.world.suppliers)
        slots = [(keys[i % len(keys)], set[str]()) for i in range(n)]
        rng.shuffle(slots)
        scale = n / 60
        for case, (count, layouts) in QUOTAS.items():
            want = max(1, round(count * scale))
            free = [
                s
                for s in slots
                if self.world.layout_of[s[0]] in layouts
                and not (
                    s[1]
                    & {"credit_note", "credit_note_unknown_original", "proforma", "duplicate_file"}
                )
                and not (
                    case
                    in {"credit_note", "proforma", "duplicate_file", "credit_note_unknown_original"}
                    and s[1]
                )
            ]
            for s in rng.sample(free, min(want, len(free))):
                s[1].add(case)
        return slots

    def build(self) -> InvoiceSet:
        for split, n in SPLITS.items():
            rng = random.Random(f"invoices/{self.seed}/{split}")
            done: list[Invoice] = []
            for idx, (supplier_key, cases) in enumerate(self._plan(rng, n), start=1):
                if "duplicate_file" in cases:
                    continue  # copies are made after their originals exist
                inv = self._invoice(rng, split, idx, supplier_key, cases)
                done.append(inv)
                self.out.findings[inv.invoice_id] = self._erp(rng, inv)
                if "iban_changed" in cases:
                    iban = make_iban(rng, inv.supplier.country)  # drawn always: the rest stays put
                    if "unknown_supplier" in cases:
                        inv.edge_cases.discard("iban_changed")  # no record to differ from
                    else:
                        inv.printed_iban = iban
                        self.out.findings[inv.invoice_id].append(Finding("iban_changed"))
                if "unknown_supplier" in cases:
                    self.out.findings[inv.invoice_id].append(Finding("unknown_supplier"))
                if "truncated" in cases:
                    self.out.findings[inv.invoice_id].append(Finding("pages_missing"))
            self._pair_credit_notes_and_proformas(rng, done)
            self._duplicates(rng, split, n, done)
            self.out.invoices.extend(done)
        return self.out

    def _pair_credit_notes_and_proformas(self, rng: random.Random, done: list[Invoice]) -> None:
        by_supplier: dict[str, list[Invoice]] = {}
        for inv in done:
            if inv.kind is DocKind.INVOICE:
                by_supplier.setdefault(inv.supplier.key, []).append(inv)
        for inv in done:
            if inv.kind is DocKind.CREDIT_NOTE:
                originals = by_supplier.get(inv.supplier.key, [])
                if "credit_note_unknown_original" in inv.edge_cases or not originals:
                    inv.original_number = self._number(rng, inv.layout, DocKind.INVOICE)
                    self._numbers.discard(inv.original_number)
                    self.out.findings[inv.invoice_id].append(Finding("unknown_original"))
                else:
                    inv.original_number = rng.choice(originals).number
            if inv.kind is DocKind.PROFORMA:
                candidates = [
                    o for o in by_supplier.get(inv.supplier.key, []) if o.proforma_number is None
                ]
                if candidates:
                    final = rng.choice(candidates)
                    final.proforma_number = inv.number
                    final.proforma_settled = min(inv.total, final.total)
                    final.edge_cases.add("proforma_settled")
                    compute(final)

    def _duplicates(self, rng: random.Random, split: str, n: int, done: list[Invoice]) -> None:
        want = max(1, round(QUOTAS["duplicate_file"][0] * n / 60))
        sources = [
            i for i in done if i.kind is DocKind.INVOICE and not i.edge_cases & {"truncated"}
        ]
        for k, src in enumerate(rng.sample(sources, min(want, len(sources))), start=1):
            copy = replace(
                src,
                invoice_id=f"{split[:2].upper()}-D{k:03d}",
                duplicate_of=src.invoice_id,
                edge_cases=src.edge_cases | {"duplicate_file"},
            )
            done.append(copy)
            # The same file carries the same problems, and is a duplicate on top of them.
            self.out.findings[copy.invoice_id] = [
                *self.out.findings[src.invoice_id],
                Finding("duplicate", detail=src.invoice_id),
            ]


def agreed_price(layout: Layout, ln: Line) -> Decimal:
    """The net unit price after discounts that the order agreed, before any planted change."""
    if layout is Layout.POHODA:
        return ln.unit_price * (1 - ln.discount_pct / 100)
    return ln.net_unit_price


def build_invoice_set(seed: int) -> InvoiceSet:
    return InvoiceSampler(seed).build()
