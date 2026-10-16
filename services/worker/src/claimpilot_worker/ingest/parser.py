"""Document parsing with Docling: text blocks with page and bounding box, tables split into rows.

Runs in the native worker with the MPS accelerator. OCR uses Apple Vision (ocrmac) on macOS and
RapidOCR elsewhere. Pages with a text layer keep it; image regions and scanned pages are OCR'd.

Docling's layout model sometimes files a letterhead, a form or a stamp as a picture and keeps the
OCR text as the picture's children; running page headers and footers sit in the furniture layer.
Both are read here: they hold patient names, visit dates, diagnoses and file references. Bare
page numbers ("1 / 2") are dropped.
After a change here, rebuild the eval parse cache (`claimpilot-eval reparse`).
"""

import hashlib
import re
import sys
import time
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pymupdf
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import OcrMacOptions, PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption
from docling_core.types.doc.base import BoundingBox
from docling_core.types.doc.common.content_layer import ContentLayer
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.table.table import TableItem
from docling_core.types.doc.items.text import TextItem

from claimpilot_core.schemas.parsing import Block, FracBox, PageInfo, ParsedDocument
from claimpilot_core.settings import get_settings
from claimpilot_worker.ingest.hidden_text import hidden_spans, mark_hidden

OCR_LANGS_MAC = ["iso:cs", "iso:de", "iso:it", "iso:en", "iso:pl", "iso:tr"]
PAGE_NUMBER = re.compile(r"\d+\s*/\s*\d+")
FURNITURE = {"page_header", "page_footer"}
MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def converter() -> DocumentConverter:
    if sys.platform == "darwin":
        ocr = OcrMacOptions(lang=OCR_LANGS_MAC)
        device = AcceleratorDevice.MPS
    else:
        ocr = RapidOcrOptions()
        device = AcceleratorDevice.CPU
    opts = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        ocr_options=ocr,
        accelerator_options=AcceleratorOptions(device=device, num_threads=8),
    )
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=opts),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=opts),
        }
    )


def _frac(bbox: BoundingBox, width: float, height: float) -> FracBox:
    tl = bbox.to_top_left_origin(page_height=height)
    clamp = lambda v: max(0.0, min(1.0, v))  # noqa: E731
    return FracBox(
        x0=clamp(tl.l / width),
        y0=clamp(tl.t / height),
        x1=clamp(tl.r / width),
        y1=clamp(tl.b / height),
    )


def _text_layer_chars(path: Path) -> dict[int, int]:
    if path.suffix.lower() != ".pdf":
        return {}
    with pymupdf.open(path) as doc:
        return {(p.number or 0) + 1: len(str(p.get_text()).strip()) for p in doc}


def blocks_from(doc: DoclingDocument, pages: dict[int, PageInfo]) -> list[Block]:
    """Text blocks in reading order: body text, text inside pictures, running headers and footers,
    and one block per table row."""
    blocks: list[Block] = []

    def add(page: int, kind: str, text: str, box: FracBox) -> None:
        text = " ".join(text.split())
        if kind in FURNITURE and PAGE_NUMBER.fullmatch(text):
            return
        if text:
            blocks.append(
                Block(
                    page=page,
                    seq=len(blocks),
                    kind=kind,
                    text=text,
                    bbox=box,
                    ocr=pages[page].text_chars == 0,
                )
            )

    for item, _level in doc.iterate_items(
        included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE},
        traverse_pictures=True,
    ):
        provs = getattr(item, "prov", None)
        if not provs:
            continue
        prov = provs[0]
        page = pages[prov.page_no]
        if isinstance(item, TableItem):
            rows: dict[int, list] = defaultdict(list)
            for cell in item.data.table_cells:
                if cell.bbox is not None and cell.text.strip():
                    rows[cell.start_row_offset_idx].append(cell)
            for _, cells in sorted(rows.items()):
                cells.sort(key=lambda c: c.start_col_offset_idx)
                box = _frac(cells[0].bbox, page.width, page.height)
                for c in cells[1:]:
                    box = box.union(_frac(c.bbox, page.width, page.height))
                add(page.page, "table_row", " | ".join(c.text.strip() for c in cells), box)
        elif isinstance(item, TextItem):
            add(page.page, str(item.label), item.text, _frac(prov.bbox, page.width, page.height))
    return blocks


def parse(path: Path, *, tables: bool = False) -> ParsedDocument:
    """Blocks of the document, with text a reader cannot see marked as hidden. With `tables`
    (invoices) the document is read from its words instead of Docling: blocks are visual lines
    and line-item tables are rebuilt into `cells` (ingest/tables.py). Claims leave it off, so
    their parse output stays as it was."""
    if tables:
        return parse_invoice(path)
    return mark_hidden(_parse(path), hidden_spans(path))


def parse_invoice(path: Path) -> ParsedDocument:
    from claimpilot_worker.ingest.tables import _visible, line_blocks, page_words, table_cells

    started = time.perf_counter()
    chars = _text_layer_chars(path)
    with pymupdf.open(path) as doc:
        pages = [
            PageInfo(
                page=(p.number or 0) + 1,
                width=p.rect.width,
                height=p.rect.height,
                text_chars=chars.get((p.number or 0) + 1, 0),
            )
            for p in doc
        ]
    spans = hidden_spans(path)
    words = page_words(path, pages)
    blocks = line_blocks(words, spans)
    if not any(p.text_chars for p in pages):
        blocks = [b.model_copy(update={"ocr": True}) for b in blocks]
    return ParsedDocument(
        sha256=sha256_file(path),
        mime_type=MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream"),
        pages=pages,
        blocks=blocks,
        cells=table_cells(_visible(words, spans)),
        parser="words",
        seconds=round(time.perf_counter() - started, 2),
    )


def _parse(path: Path) -> ParsedDocument:
    settings = get_settings()
    if settings.ocr_engine == "textract":
        from claimpilot_worker.ingest.textract import TextractReader, is_scan

        if is_scan(path):
            return TextractReader(settings.aws_region).parse(path)
    started = time.perf_counter()
    result = converter().convert(path)
    doc = result.document
    chars = _text_layer_chars(path)
    pages = {
        no: PageInfo(page=no, width=p.size.width, height=p.size.height, text_chars=chars.get(no, 0))
        for no, p in doc.pages.items()
    }
    return ParsedDocument(
        sha256=sha256_file(path),
        mime_type=MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream"),
        pages=sorted(pages.values(), key=lambda p: p.page),
        blocks=blocks_from(doc, pages),
        seconds=round(time.perf_counter() - started, 2),
    )
