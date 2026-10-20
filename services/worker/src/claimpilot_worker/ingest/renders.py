"""Page renders for the review UI and the vision path, cached next to the upload."""

import io
import math
from pathlib import Path

import pymupdf
from PIL import Image

RENDER_DPI = 110
# A page is rendered to at most this many pixels (36 MP is 108 MB as RGB). A page that would need
# its resolution cut by more than MAX_DOWNSCALE to fit is refused: a MediaBox of 200 000 pt would
# otherwise allocate gigabytes.
MAX_RENDER_PIXELS = 36_000_000
MAX_DOWNSCALE = 4


class PageTooLargeError(ValueError):
    pass


def capped_dpi(width_pt: float, height_pt: float, dpi: float) -> float:
    """`dpi`, or less when the page would exceed MAX_RENDER_PIXELS at that resolution."""
    pixels = (width_pt * dpi / 72) * (height_pt * dpi / 72)
    if pixels <= MAX_RENDER_PIXELS:
        return dpi
    scale = math.sqrt(MAX_RENDER_PIXELS / pixels)
    if scale < 1 / MAX_DOWNSCALE:
        raise PageTooLargeError(f"page of {width_pt:.0f} x {height_pt:.0f} pt is too large")
    return dpi * scale


def _pixmap(page: pymupdf.Page, dpi: float) -> pymupdf.Pixmap:
    zoom = capped_dpi(page.rect.width, page.rect.height, dpi) / 72
    return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))


def render_pages(path: Path, out_dir: Path, *, dpi: int = RENDER_DPI) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as doc:
            for page in doc:
                target = out_dir / f"p{(page.number or 0) + 1}.png"
                if not target.exists():
                    _pixmap(page, dpi).save(target)
                outputs.append(target)
    else:
        target = out_dir / "p1.png"
        if not target.exists():
            with Image.open(path) as img:
                img.convert("RGB").save(target, format="PNG")
        outputs.append(target)
    return outputs


def page_png_b64(path: Path, page: int, *, max_side: int = 1600) -> str:
    """A page image for the vision model, scaled so the longest side is at most `max_side` px."""
    import base64

    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as doc:
            pix = _pixmap(doc[page - 1], 170)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    else:
        img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
