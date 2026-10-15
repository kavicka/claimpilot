"""Turning a Docling document into blocks, on a hand-built document (no Docling model run)."""

from docling_core.types.doc import (
    BoundingBox,
    ContentLayer,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
)

from claimpilot_core.schemas.parsing import PageInfo
from claimpilot_worker.ingest.parser import blocks_from


def prov(l, t, r, b) -> ProvenanceItem:  # noqa: E741 - Docling's names for the box sides
    return ProvenanceItem(
        page_no=1, bbox=BoundingBox.from_tuple((l, t, r, b), origin="TOPLEFT"), charspan=(0, 0)
    )


def scan() -> DoclingDocument:
    doc = DoclingDocument(name="medical_report")
    doc.add_page(page_no=1, size=Size(width=100, height=200))
    doc.add_text(
        label=DocItemLabel.PAGE_HEADER,
        text="Ärztlicher Befundbericht",
        prov=prov(10, 2, 60, 6),
        content_layer=ContentLayer.FURNITURE,
    )
    letterhead = doc.add_picture(prov=prov(5, 10, 95, 60))
    doc.add_text(
        label=DocItemLabel.TEXT,
        text="PATIENT/IN Nataša Pavúková",
        prov=prov(8, 20, 70, 26),
        parent=letterhead,
    )
    doc.add_text(label=DocItemLabel.TEXT, text="Keine Vorerkrankungen.", prov=prov(8, 80, 90, 90))
    doc.add_text(
        label=DocItemLabel.PAGE_FOOTER,
        text="1 / 1",
        prov=prov(45, 190, 55, 195),
        content_layer=ContentLayer.FURNITURE,
    )
    return doc


def test_text_inside_pictures_and_running_headers_becomes_blocks():
    pages = {1: PageInfo(page=1, width=100, height=200)}
    blocks = blocks_from(scan(), pages)
    assert [(b.kind, b.text) for b in blocks] == [
        ("page_header", "Ärztlicher Befundbericht"),
        ("text", "PATIENT/IN Nataša Pavúková"),
        ("text", "Keine Vorerkrankungen."),
    ]  # the bare page number is dropped
    name = blocks[1]
    assert (name.bbox.x0, name.bbox.y0, name.bbox.x1, name.bbox.y1) == (0.08, 0.1, 0.7, 0.13)
    assert all(b.ocr for b in blocks)  # no text layer on the page
