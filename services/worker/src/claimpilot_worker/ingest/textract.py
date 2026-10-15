"""OCR through Amazon Textract (Phase 2 option; Docling with RapidOCR stays the default).

DetectDocumentText returns LINE blocks whose bounding box is fractional with a top-left origin,
the convention FracBox uses, so each line becomes a Block as it is. With
CLAIMPILOT_OCR_ENGINE=textract, scans and photos are read here; PDFs with a text layer keep
Docling. Masking keeps RapidOCR's detector either way: it runs inside the task.

Textract may keep document inputs to improve the service unless the AWS Organizations AI
services opt-out policy is set (docs/research/aws-bedrock-facts.md, section 5). docs/deploy.md
makes the opt-out a precondition for this engine.
"""

import hashlib
import io
import time
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image

from claimpilot_core.schemas.parsing import Block, FracBox, PageInfo, ParsedDocument

DPI = 200  # Textract reads 150-300 dpi best
MIME_BY_SUFFIX = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def is_scan(path: Path) -> bool:
    """An image file, or a PDF none of whose pages has a text layer."""
    if path.suffix.lower() != ".pdf":
        return True
    with pymupdf.open(path) as doc:
        return all(not str(p.get_text()).strip() for p in doc)


def _pages(path: Path) -> list[Image.Image]:
    if path.suffix.lower() != ".pdf":
        return [Image.open(path).convert("RGB")]
    out = []
    with pymupdf.open(path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=DPI)
            out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return out


class TextractReader:
    def __init__(self, region: str, *, client: Any = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("textract", region_name=region)
        self._client = client

    def lines(self, img: Image.Image) -> list[tuple[str, FracBox]]:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out = self._client.detect_document_text(Document={"Bytes": buf.getvalue()})
        lines = []
        for block in out.get("Blocks", []):
            if block.get("BlockType") != "LINE" or not block.get("Text", "").strip():
                continue
            box = block["Geometry"]["BoundingBox"]
            clamp = lambda v: max(0.0, min(1.0, float(v)))  # noqa: E731
            lines.append(
                (
                    " ".join(block["Text"].split()),
                    FracBox(
                        x0=clamp(box["Left"]),
                        y0=clamp(box["Top"]),
                        x1=clamp(box["Left"] + box["Width"]),
                        y1=clamp(box["Top"] + box["Height"]),
                    ),
                )
            )
        return lines

    def parse(self, path: Path) -> ParsedDocument:
        started = time.perf_counter()
        pages, blocks = [], []
        for n, img in enumerate(_pages(path), start=1):
            pages.append(PageInfo(page=n, width=img.width, height=img.height, text_chars=0))
            for text, box in self.lines(img):
                blocks.append(
                    Block(page=n, seq=len(blocks), kind="text", text=text, bbox=box, ocr=True)
                )
        return ParsedDocument(
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            mime_type=MIME_BY_SUFFIX.get(path.suffix.lower(), "image/png"),
            pages=pages,
            blocks=blocks,
            seconds=round(time.perf_counter() - started, 2),
        )
