"""Render documents to PDF, make scan and photo variants, and locate PII on the page."""

import io
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pymupdf as fitz
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from PIL import Image, ImageDraw, ImageFilter, ImageFont


def _homebrew_dlopen_shim() -> None:
    """uv's Python does not search /opt/homebrew/lib, where pango and gobject live on macOS."""
    import cffi

    original = cffi.FFI.dlopen

    def dlopen(self, name, flags=0):
        try:
            return original(self, name, flags)
        except OSError:
            if isinstance(name, str) and "/" not in name:
                for candidate in (f"/opt/homebrew/lib/{name}.dylib", f"/opt/homebrew/lib/{name}"):
                    if os.path.exists(candidate):
                        return original(self, candidate, flags)
            raise

    cffi.FFI.dlopen = dlopen


if sys.platform == "darwin":
    _homebrew_dlopen_shim()
from weasyprint import HTML

from claimpilot_datagen.documents import Built
from claimpilot_datagen.i18n import LABELS
from claimpilot_datagen.model import DocSpec

TEMPLATES = Path(__file__).parent / "templates"
_ENV = Environment(loader=FileSystemLoader(TEMPLATES), undefined=StrictUndefined, autoescape=True)
_CSS = (TEMPLATES / "base.css").read_text(encoding="utf-8")
STAMP_FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


@dataclass
class Rendered:
    data: bytes
    ext: str  # pdf | jpg | png
    pages: int
    pii: list[dict]
    dpi: int | None = None  # scans: PII positions stay in PDF points; pixels = points * dpi / 72


def render_pdf(built: Built) -> bytes:
    labels = LABELS.get(built.context["lang"], LABELS["en"])
    html = _ENV.get_template(built.template).render(css=_CSS, L=labels, **built.context)
    pdf = HTML(string=html, base_url=str(TEMPLATES)).write_pdf()
    assert pdf is not None
    return pdf


def locate_pii(pdf: bytes, pii: list[tuple[str, str]]) -> list[dict]:
    """Find every PII value on the rendered pages (before any scan effect)."""
    out = []
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        for entity, value in pii:
            hits = []
            for page in doc:
                for rect in page.search_for(value.replace(" ", " ")):
                    hits.append(
                        {"page": (page.number or 0) + 1, "bbox": [round(v, 1) for v in rect]}
                    )
            out.append({"type": entity, "value": value, "found": bool(hits), "positions": hits})
    return out


def _stamp(img: Image.Image, rng: random.Random, text: str) -> None:
    w, h = img.size
    layer = Image.new("RGBA", (int(w * 0.36), int(h * 0.07)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    try:
        font = ImageFont.truetype(STAMP_FONT, int(h * 0.024))
    except OSError:
        font = ImageFont.load_default()
    color = (170, 20, 30, 170) if rng.random() < 0.6 else (25, 40, 150, 170)
    draw.rectangle([2, 2, layer.width - 3, layer.height - 3], outline=color, width=4)
    draw.text((layer.width * 0.08, layer.height * 0.25), text, fill=color, font=font)
    layer = layer.rotate(rng.uniform(-12, 12), expand=True)
    img.paste(layer, (int(w * rng.uniform(0.45, 0.6)), int(h * rng.uniform(0.04, 0.12))), layer)


def _degrade(img: Image.Image, rng: random.Random) -> Image.Image:
    img = img.convert("RGB")
    _stamp(img, rng, rng.choice(["PRIJATÉ", "DORUČENÉ", "KÓPIA"]))
    img = img.rotate(
        rng.uniform(-3, 3),
        resample=Image.Resampling.BICUBIC,
        expand=False,
        fillcolor=(248, 247, 242),
    )
    arr = np.asarray(img).astype(np.float32)
    arr = arr * rng.uniform(0.9, 0.98) + rng.uniform(4, 14)  # paper tone
    noise = np.random.default_rng(rng.randrange(2**32)).normal(0, rng.uniform(4, 11), arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    return img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.9)))


def _jpeg(img: Image.Image, rng: random.Random) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=rng.randint(45, 78))
    return buf.getvalue()


def scan_variant(pdf: bytes, spec: DocSpec, rng: random.Random) -> tuple[bytes, str, int, int]:
    """Rasterize at 150-200 dpi with scan artifacts. Returns bytes, extension and page count."""
    dpi = rng.choice([150, 170, 200])
    pages: list[Image.Image] = []
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            pages.append(_degrade(img, rng))
    if spec.image_format and len(pages) == 1:
        buf = io.BytesIO()
        if spec.image_format == "png":
            pages[0].save(buf, format="PNG", optimize=True)
        else:
            buf.write(_jpeg(pages[0], rng))
        return buf.getvalue(), spec.image_format, 1, dpi
    out = fitz.open()
    for img in pages:
        data = _jpeg(img, rng)
        w_pt, h_pt = img.width * 72 / dpi, img.height * 72 / dpi
        page = out.new_page(width=w_pt, height=h_pt)
        page.insert_image(page.rect, stream=data)
    blob = out.tobytes(deflate=True, no_new_id=True)  # no random /ID, so reruns are byte-identical
    out.close()
    return blob, "pdf", len(pages), dpi


def render(built: Built, spec: DocSpec, rng: random.Random) -> Rendered:
    pdf = render_pdf(built)
    pii = locate_pii(pdf, built.pii)
    if spec.scan:
        data, ext, pages, dpi = scan_variant(pdf, spec, rng)
        return Rendered(data, ext, pages, pii, dpi)
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        pages = doc.page_count
    return Rendered(pdf, "pdf", pages, pii)
