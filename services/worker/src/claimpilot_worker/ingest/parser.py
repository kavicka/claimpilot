"""Document parsing with Docling: text blocks with page and bounding box, tables split into rows.

Runs in the native worker with the MPS accelerator. OCR uses Apple Vision (ocrmac) on macOS and
RapidOCR elsewhere. Pages with a text layer keep it; image regions and scanned pages are OCR'd.
"""

import hashlib
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
from docling_core.types.doc.items.table.table import TableItem
from docling_core.types.doc.items.text import TextItem

from claimpilot_core.schemas.parsing import Block, FracBox, PageInfo, ParsedDocument

OCR_LANGS_MAC = ["iso:cs", "iso:de", "iso:it", "iso:en", "iso:pl", "iso:tr"]
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


def parse(path: Path) -> ParsedDocument:
    started = time.perf_counter()
    result = converter().convert(path)
    doc = result.document
    chars = _text_layer_chars(path)
    pages = {
        no: PageInfo(page=no, width=p.size.width, height=p.size.height, text_chars=chars.get(no, 0))
        for no, p in doc.pages.items()
    }
    blocks: list[Block] = []

    def add(page: int, kind: str, text: str, box: FracBox) -> None:
        text = " ".join(text.split())
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

    for item, _level in doc.iterate_items():
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
    return ParsedDocument(
        sha256=sha256_file(path),
        mime_type=MIME_BY_SUFFIX.get(path.suffix.lower(), "application/octet-stream"),
        pages=sorted(pages.values(), key=lambda p: p.page),
        blocks=blocks,
        seconds=round(time.perf_counter() - started, 2),
    )
