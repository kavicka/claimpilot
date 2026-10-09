"""Page renders for the review UI and the vision path, cached next to the upload."""

import io
from pathlib import Path

import pymupdf
from PIL import Image

RENDER_DPI = 110


def render_pages(path: Path, out_dir: Path, *, dpi: int = RENDER_DPI) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as doc:
            for page in doc:
                target = out_dir / f"p{(page.number or 0) + 1}.png"
                if not target.exists():
                    page.get_pixmap(dpi=dpi).save(target)
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
            pix = doc[page - 1].get_pixmap(dpi=170)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    else:
        img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
