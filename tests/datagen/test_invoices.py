"""Invoice generator invariants: the set must be consistent before anything is scored on it."""

from collections import Counter, defaultdict
from dataclasses import asdict
from decimal import Decimal

import pymupdf as fitz
import pytest

from claimpilot_core.identifiers import is_valid_iban
from claimpilot_core.trade_ids import is_valid_ico, is_valid_vat_id, normalize_gtin
from claimpilot_datagen.invoices.model import DocKind, Layout, VatMethod
from claimpilot_datagen.invoices.render import render
from claimpilot_datagen.invoices.sampler import PRICE_DIFF, QUOTAS, SPLITS, build_invoice_set

PLANTED = {  # edge case -> the finding it must raise
    "price_diff": "price_diff",
    "short_delivery": "short_delivery",
    "iban_changed": "iban_changed",
    "unknown_supplier": "unknown_supplier",
    "truncated": "pages_missing",
    "duplicate_file": "duplicate",
    "credit_note_unknown_original": "unknown_original",
}


@pytest.fixture(scope="module")
def iset():
    return build_invoice_set(42)


def test_split_sizes(iset):
    assert Counter(i.split for i in iset.invoices) == SPLITS


@pytest.mark.parametrize("split", ["dev", "test"])
def test_every_planted_case_is_in_dev_and_test(iset, split):
    cases = Counter(c for i in iset.invoices if i.split == split for c in i.edge_cases)
    for case in QUOTAS:
        assert cases[case] >= 1, case
    assert set(Layout) == {i.layout for i in iset.invoices if i.split == split}
    assert {DocKind.CREDIT_NOTE, DocKind.PROFORMA} <= {
        i.kind for i in iset.invoices if i.split == split
    }


def test_arithmetic(iset):
    for inv in iset.invoices:
        bases: dict[int, Decimal] = defaultdict(Decimal)
        for ln in inv.lines:
            bases[ln.vat_rate] += ln.line_net
        for fee in inv.fees:
            if not fee.included:
                bases[0 if inv.reverse_charge else fee.vat_rate] += fee.net
        assert {r.rate: r.base for r in inv.recap} == dict(bases), inv.invoice_id
        for r in inv.recap:
            if inv.vat_method is VatMethod.PER_RATE:
                assert r.vat == (r.base * r.rate / 100).quantize(Decimal("0.01"), "ROUND_HALF_UP")
            else:
                assert abs(r.vat - r.base * r.rate / 100) <= Decimal("0.005") * (len(inv.lines) + 1)
        assert inv.total == inv.total_net + inv.total_vat
        assert inv.amount_due == inv.total - inv.proforma_settled
        if inv.reverse_charge:
            assert inv.total_vat == 0
        if inv.kind is DocKind.CREDIT_NOTE:
            assert inv.total < 0 and all(ln.qty < 0 for ln in inv.lines)
        else:
            assert inv.total > 0


def test_identifiers(iset):
    for inv in iset.invoices:
        for party in (inv.supplier, inv.buyer):
            assert is_valid_ico(party.ico) and is_valid_vat_id(party.vat_id)
            assert is_valid_iban(party.iban)
        assert is_valid_iban(inv.iban)
        for ln in inv.lines:
            if ln.printed_ean is None:
                assert inv.layout is Layout.TANGRAM
                continue
            gtin = normalize_gtin(ln.printed_ean)
            assert gtin.gtin is not None and gtin.gtin.zfill(13) == ln.product.ean
            assert ("padded" in gtin.flags) == (len(ln.printed_ean) == 11)


def test_planted_cases_raise_their_findings_and_nothing_else(iset):
    for inv in iset.invoices:
        kinds = {f.kind for f in iset.findings[inv.invoice_id]}
        expected = {PLANTED[c] for c in inv.edge_cases if c in PLANTED}
        assert kinds == expected, (inv.invoice_id, inv.edge_cases, kinds)


def test_erp_records_match_the_invoices(iset):
    orders = {o.number: o for o in iset.orders}
    receipts = defaultdict(list)
    for r in iset.receipts:
        receipts[r.order_number].append(r)
    for inv in iset.invoices:
        registered = inv.supplier.key not in iset.unregistered_suppliers
        if inv.kind is DocKind.CREDIT_NOTE or not registered:
            assert inv.order_number not in orders or inv.duplicate_of
            continue
        order = orders[inv.order_number]
        findings = {(f.kind, f.line) for f in iset.findings[inv.invoice_id]}
        for i, (ln, ol) in enumerate(zip(inv.lines, order.lines, strict=True)):
            assert ol.qty == ln.qty
            invoiced = (
                ln.unit_price * (1 - ln.discount_pct / 100)
                if inv.layout is Layout.POHODA
                else ln.net_unit_price
            )
            if ("price_diff", i) in findings:
                assert invoiced / ol.unit_price > Decimal("1.015")
                assert invoiced / ol.unit_price < PRICE_DIFF + Decimal("0.01")
            else:
                assert invoiced == ol.unit_price
        if inv.kind is DocKind.INVOICE:
            (receipt,) = receipts[inv.order_number][:1]
            for i, (ln, rl) in enumerate(zip(inv.lines, receipt.lines, strict=True)):
                assert (rl.qty < ln.qty) == (("short_delivery", i) in findings)


def test_credit_notes_point_at_a_real_invoice_unless_planted(iset):
    numbers = {(i.supplier.key, i.number) for i in iset.invoices if i.kind is DocKind.INVOICE}
    for inv in iset.invoices:
        if inv.kind is DocKind.CREDIT_NOTE:
            known = (inv.supplier.key, inv.original_number) in numbers
            assert known != ("credit_note_unknown_original" in inv.edge_cases) or not known


def test_proformas_are_settled_by_a_later_invoice(iset):
    settled = {i.proforma_number for i in iset.invoices if i.proforma_number}
    for inv in iset.invoices:
        if inv.kind is DocKind.PROFORMA:
            assert inv.number in settled


def test_the_set_is_deterministic(iset):
    again = build_invoice_set(42)
    assert [asdict(i) for i in again.invoices] == [asdict(i) for i in iset.invoices]
    assert again.findings == iset.findings


# --- rendering: ground truth is what the page shows ------------------------------------------


def _sample(iset):
    dev = [i for i in iset.invoices if i.split == "dev"]
    picked = {}
    for inv in dev:
        for key in (inv.layout.value, inv.kind.value, *inv.edge_cases):
            picked.setdefault(key, inv)
    return list({i.invoice_id: i for i in picked.values()}.values())


def _printed(gt_part):
    if isinstance(gt_part, dict):
        if "printed" in gt_part:
            yield gt_part["printed"]
        else:
            for v in gt_part.values():
                yield from _printed(v)
    elif isinstance(gt_part, list):
        for v in gt_part:
            yield from _printed(v)


@pytest.fixture(scope="module")
def rendered(iset):
    return [(inv, *render(inv, 42)) for inv in _sample(iset)]


def test_every_printed_value_is_on_the_page(rendered):
    for inv, data, _ext, v in rendered:
        if inv.layout is Layout.SCAN_EN:
            continue  # an image: covered by the extraction eval, not by text search
        with fitz.open(stream=data, filetype="pdf") as doc:
            text = " ".join(" ".join(str(p.get_text()).split()) for p in doc)
        parts = [f for f in v["header"].values() if f["page"] is not None]
        parts += [x for x in [*v["recap"], *v["fees"], *v["lines"]] if x["page"] is not None]
        missing = [
            p for p in _printed(parts) if " ".join(str(p).split()) not in text and len(str(p)) > 1
        ]
        assert not missing, (inv.invoice_id, inv.layout, missing[:5])


def test_page_facts(rendered):
    for inv, data, _ext, v in rendered:
        with fitz.open(stream=data, filetype="pdf") as doc:
            pages = doc.page_count
            text = " ".join(str(p.get_text()) for p in doc)
        assert pages == inv.pages_present
        if "truncated" in inv.edge_cases:
            assert inv.pages_total > 1 and pages == 1
            assert any(ln["page"] is None for ln in v["lines"])
            assert v["header"]["amount_due"]["page"] is None
        else:
            assert all(ln["page"] is not None for ln in v["lines"]), inv.invoice_id
        if "duplicated_page" in inv.edge_cases:
            assert "Strana null/1" in text
        if inv.layout is Layout.SCAN_EN:
            assert not text.strip() and v["scan_dpi"]
