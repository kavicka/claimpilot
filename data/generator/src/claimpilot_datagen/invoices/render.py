"""Render invoices to PDF (or a scan), find the page of every line, write ground truth."""

import hashlib
import json
import random
import shutil
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pymupdf as fitz
from jinja2 import Environment, FileSystemLoader

from claimpilot_datagen.invoices.fmt import STYLES
from claimpilot_datagen.invoices.model import Invoice, Layout
from claimpilot_datagen.invoices.present import view
from claimpilot_datagen.invoices.sampler import SPLITS, InvoiceSet, build_invoice_set
from claimpilot_datagen.invoices.terms import TERMS
from claimpilot_datagen.render import TEMPLATES, scan_variant

GENERATOR_VERSION = "invoices-1"
# Lenient undefined: templates test optional fields (`{% if h.order_number %}`); the as-printed
# test catches a field that should have been printed and was not.
_ENV = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)


def render_html(inv: Invoice, v: dict[str, Any]) -> str:
    st = STYLES[inv.layout]
    recap2 = []
    if inv.fx_rate:
        for r in inv.recap:
            recap2.append(
                {
                    "base": st.amount((r.base * inv.fx_rate).quantize(Decimal("0.01"))),
                    "vat": st.amount((r.vat * inv.fx_rate).quantize(Decimal("0.01"))),
                }
            )
    return _ENV.get_template(f"invoices/{inv.layout.value}.html.j2").render(
        **v, recap2=recap2, terms=TERMS, lang="en" if inv.layout is Layout.SCAN_EN else "sk"
    )


def render_pdf(html: str) -> bytes:
    from weasyprint import HTML  # after claimpilot_datagen.render installed its dlopen shim

    pdf = HTML(string=html, base_url=str(TEMPLATES)).write_pdf()
    assert pdf is not None
    return pdf


def _locate_lines(pdf: bytes, v: dict[str, Any]) -> None:
    """The page each line is printed on. Lines are searched in order, so a line printed twice
    (the same product on two lines) gets the later occurrence for its second copy."""
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        texts = [" ".join(str(p.get_text()).split()) for p in doc]
    page, offset = 0, 0
    for ln in v["lines"]:
        needle = " ".join(str(ln["cells"]["name"]["printed"]).split()[:3])
        while page < len(texts):
            at = texts[page].find(needle, offset)
            if at >= 0:
                ln["page"], offset = page + 1, at + len(needle)
                break
            page, offset = page + 1, 0


# Fields printed after the line items, and the words that mark where that block starts.
TAIL = {
    Layout.WHOLESALE: ("Spolu", {"total", "amount_due", "delivery_note_numbers", "currency"}),
    Layout.SAP: ("Celkom k platbe", {"total_net", "total_vat", "total", "amount_due",
                                     "second_currency_total", "fx_rate", "reverse_charge"}),
    Layout.TANGRAM: ("K ÚHRADE", set()),
    Layout.POHODA: ("SPOLU NA ÚHRADU", {"total_net", "total_vat", "total", "amount_due",
                                         "proforma_settled"}),
    Layout.SCAN_EN: ("Total Due", {"total", "amount_due", "reverse_charge"}),
}  # fmt: skip
RECAP_AT_TOP = {Layout.TANGRAM}
# The page counter of page 1, as each layout prints it (SAP prints none).
PAGE_NOTE = {
    Layout.WHOLESALE: "strana 1 z {n}",
    Layout.SAP: None,
    Layout.TANGRAM: "Strana 1/{n}",
    Layout.POHODA: "Strana 1 dokladu {number}",
    Layout.SCAN_EN: "Page: 1/{n}",
}


def _place_fields(pdf: bytes, inv: Invoice, v: dict[str, Any]) -> None:
    """Every header field, recap row and fee gets the page it is printed on."""
    marker, tail_fields = TAIL[inv.layout]
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        pages = [str(p.get_text()) for p in doc]
    tail = next((i + 1 for i in reversed(range(len(pages))) if marker in pages[i]), 1)
    for key, field in v["header"].items():
        field["page"] = tail if key in tail_fields else 1
    note = PAGE_NOTE[inv.layout]
    if note:
        printed = note.format(n=inv.pages_total, number=inv.number)
        v["header"]["page_note"] = {"printed": printed, "value": printed, "page": 1}
    for row in v["recap"]:
        row["page"] = 1 if inv.layout in RECAP_AT_TOP else tail
    for fee in v["fees"]:
        fee["page"] = tail


def _first_page(pdf: bytes) -> bytes:
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        doc.select([0])
        return doc.tobytes(deflate=True, no_new_id=True)


def render(inv: Invoice, seed: int) -> tuple[bytes, str, dict[str, Any]]:
    v = view(inv)
    pdf = render_pdf(render_html(inv, v))
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        inv.pages_total = inv.pages_present = doc.page_count
    _locate_lines(pdf, v)
    _place_fields(pdf, inv, v)
    if "truncated" in inv.edge_cases:
        pdf = _first_page(pdf)
        inv.pages_present = 1
        # Whatever was printed on the missing pages is not in the file: nothing can find it.
        for item in [*v["lines"], *v["header"].values(), *v["recap"], *v["fees"]]:
            if item["page"] != 1:
                item["page"] = None
    ext, dpi = "pdf", None
    if inv.layout is Layout.SCAN_EN:
        rng = random.Random(f"{seed}/{inv.invoice_id}/scan")
        pdf, ext, _, dpi = scan_variant(pdf, SimpleNamespace(image_format=None), rng)  # pyright: ignore[reportArgumentType]
    v["scan_dpi"] = dpi
    return pdf, ext, v


def ground_truth(inv: Invoice, v: dict[str, Any], s: InvoiceSet, file: str, sha: str) -> dict:
    return {
        "invoice_id": inv.invoice_id,
        "split": inv.split,
        "layout": inv.layout.value,
        "kind": inv.kind.value,
        "file": file,
        "sha256": sha,
        "pages_total": inv.pages_total,
        "pages_present": inv.pages_present,
        "scan": inv.layout is Layout.SCAN_EN,
        "scan_dpi": v["scan_dpi"],
        "language": "en" if inv.layout is Layout.SCAN_EN else "sk",
        "duplicate_of": inv.duplicate_of,
        "edge_cases": sorted(inv.edge_cases),
        "vat_method": inv.vat_method.value,
        "supplier_key": inv.supplier.key,
        "supplier_registered": inv.supplier.key not in s.unregistered_suppliers,
        "buyer_key": inv.buyer.key,
        "delivery_point": inv.delivery_point,
        "header": v["header"],
        "lines": v["lines"],
        "recap": v["recap"],
        "fees": v["fees"],
        "findings": [asdict(f) for f in s.findings.get(inv.invoice_id, [])],
        # Personal data printed on the invoice: no model payload may carry it. The billing
        # address fakturacia@... is the company's, not a person's.
        "pii": [inv.supplier.contact, inv.supplier.phone],
    }


def _dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str) + "\n", "utf-8")


def erp_records(s: InvoiceSet, split: str) -> dict:
    ids = {i.order_number for i in s.invoices if i.split == split and i.order_number}
    orders = [o for o in s.orders if o.number in ids]
    return {
        "buyers": [asdict(b) for b in s.world.buyers.values()],
        "suppliers": [
            {**asdict(p), "layout": s.world.layout_of[k].value}
            for k, p in s.world.suppliers.items()
        ],
        "catalogue": {k: [asdict(p) for p in ps] for k, ps in s.world.catalogue.items()},
        "orders": [asdict(o) for o in orders],
        "receipts": [asdict(r) for r in s.receipts if r.order_number in ids],
    }


def generate_invoices(seed: int, out: Path, *, limit: int | None = None) -> dict:
    s = build_invoice_set(seed)
    root = out / "invoices"
    if root.exists():
        shutil.rmtree(root)
    stats: dict[str, int] = {}
    for split in SPLITS:
        sdir = root / split
        sdir.mkdir(parents=True)
        rows = []
        invoices = [i for i in s.invoices if i.split == split][:limit]
        for inv in invoices:
            idir = sdir / inv.invoice_id
            idir.mkdir()
            data, ext, v = render(inv, seed)
            name = f"{inv.kind.value}.{ext}"
            (idir / name).write_bytes(data)
            sha = hashlib.sha256(data).hexdigest()
            _dump(idir / "ground_truth.json", ground_truth(inv, v, s, name, sha))
            rows.append(
                {
                    "invoice_id": inv.invoice_id,
                    "layout": inv.layout.value,
                    "kind": inv.kind.value,
                    "file": f"{inv.invoice_id}/{name}",
                    "sha256": sha,
                    "findings": sorted({f.kind for f in s.findings.get(inv.invoice_id, [])}),
                }
            )
        _dump(
            root / f"manifest-{split}.json",
            {"seed": seed, "generator": GENERATOR_VERSION, "invoices": rows},
        )
        _dump(root / f"erp-{split}.json", erp_records(s, split))
        stats[split] = len(rows)
    return stats
