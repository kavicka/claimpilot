"""Text a reader of the PDF cannot see: white on white, a 1 pt font, outside the page, the invisible
render mode, fully transparent, or drawn over by a box or an image.

Such text is how a document talks to a model without the handler noticing. It is read from the
PDF text layer with PyMuPDF, independently of Docling, and marked on the parsed blocks:
hidden blocks never reach a model and turn into an injection signal for routing.

Invisible text lying on an image is the OCR layer of a scanned PDF, not an attack: the image is
what the reader sees. A mismatch between that layer and the image is not checked here.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from claimpilot_core.schemas.parsing import Block, FracBox, ParsedDocument

MIN_FONT_PT = 4.0
MIN_CONTRAST = 1.25  # WCAG contrast ratio; 1.0 is the same colour, body text needs 4.5
MIN_OPACITY = 0.1
COVERED = 0.9  # share of the line a later box or image must cover
ON_IMAGE = 0.8  # share of the line an earlier image must lie under to count as an OCR layer
INSIDE_PAGE = 0.5  # share of the line that must be on the page
WHITE = (1.0, 1.0, 1.0)


@dataclass(frozen=True)
class HiddenSpan:
    page: int  # 1-based
    text: str
    bbox: FracBox
    reason: str  # off_page | invisible | transparent | tiny | covered | low_contrast


def _rgb(color: Any) -> tuple[float, float, float] | None:
    if not color:
        return None
    c = tuple(float(x) for x in color)
    if len(c) == 1:
        return (c[0], c[0], c[0])
    if len(c) == 3:
        return (c[0], c[1], c[2])
    if len(c) == 4:  # CMYK
        k = c[3]
        return tuple(1 - min(1.0, x + k) for x in c[:3])  # type: ignore[return-value]
    return None


def _luminance(rgb: tuple[float, float, float]) -> float:
    def lin(v: float) -> float:
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _share(inner: pymupdf.Rect, outer: pymupdf.Rect) -> float:
    """How much of `inner` lies within `outer`, 0 to 1."""
    area = inner.get_area()
    if area <= 0:
        return 1.0 if outer.contains(inner.tl) else 0.0
    return (inner & outer).get_area() / area if inner.intersects(outer) else 0.0


@dataclass
class _Paint:
    seqno: int
    rect: pymupdf.Rect
    fill: tuple[float, float, float] | None  # None for an image


def _paints(page: pymupdf.Page) -> list[_Paint]:
    """Opaque filled rectangles and images, with their place in the drawing order. Other filled
    shapes (a signature stroke, a logo) cover little of their bounding box, so they are left out."""
    out = []
    for d in page.get_drawings():
        fill = _rgb(d.get("fill"))
        items = d.get("items", ())
        if fill is None or (d.get("fill_opacity") or 1.0) < 0.99:
            continue
        if not items or any(item[0] not in ("re", "qu") for item in items):
            continue
        if d.get("even_odd") and len(items) > 1:
            continue  # rectangles inside rectangles: a border, its middle stays empty
        for item in items:
            rect = item[1] if item[0] == "re" else item[1].rect
            out.append(_Paint(d["seqno"], pymupdf.Rect(rect), fill))
    for seqno, (kind, rect) in enumerate(page.get_bboxlog()):
        if kind == "fill-image":
            out.append(_Paint(seqno, pymupdf.Rect(rect), None))
    return out


def _lines(trace: dict) -> list[tuple[str, pymupdf.Rect]]:
    """The characters of one text run, grouped into lines by baseline."""
    rows: dict[float, list] = {}
    for ch in trace["chars"]:
        rows.setdefault(round(ch[2][1] * 2) / 2, []).append(ch)
    out = []
    for _, chars in sorted(rows.items()):
        chars.sort(key=lambda c: c[2][0])
        text = " ".join("".join(chr(c[0]) for c in chars if c[0] > 0).split())
        rect = pymupdf.Rect()
        for c in chars:
            r = pymupdf.Rect(c[3])
            if not r.is_empty:
                rect |= r
        if rect.is_empty:
            rect = pymupdf.Rect(trace["bbox"])
        if text:
            out.append((text, rect))
    return out


def _reason(
    trace: dict, rect: pymupdf.Rect, page_rect: pymupdf.Rect, paints: list[_Paint]
) -> str | None:
    seq = trace["seqno"]
    if _share(rect, page_rect) < INSIDE_PAGE:
        return "off_page"
    under = [p for p in paints if p.seqno < seq and _share(rect, p.rect) >= ON_IMAGE]
    if trace["type"] == 3:
        return None if any(p.fill is None for p in under) else "invisible"
    opacity = trace.get("opacity")
    if opacity is not None and opacity < MIN_OPACITY:
        return "transparent"
    if trace["size"] < MIN_FONT_PT:
        return "tiny"
    if any(p.seqno > seq and _share(rect, p.rect) >= COVERED for p in paints):
        return "covered"
    color = _rgb(trace.get("color"))
    behind = max(under, key=lambda p: p.seqno, default=None)
    if behind is not None and behind.fill is None:
        return None  # text on a picture: its background is unknown
    background = behind.fill if behind is not None and behind.fill is not None else WHITE
    if color is not None and contrast(color, background) < MIN_CONTRAST:
        return "low_contrast"
    return None


def hidden_spans(path: Path) -> list[HiddenSpan]:
    if path.suffix.lower() != ".pdf":
        return []
    out = []
    with pymupdf.open(path) as doc:
        for page in doc:
            page_rect = page.rect
            w, h = page_rect.width or 1, page_rect.height or 1
            paints = _paints(page)
            for trace in page.get_texttrace():
                for text, rect in _lines(trace):
                    reason = _reason(trace, rect, page_rect, paints)
                    if reason is None:
                        continue
                    clamp = lambda v: max(0.0, min(1.0, v))  # noqa: E731
                    box = FracBox(
                        x0=clamp(rect.x0 / w),
                        y0=clamp(rect.y0 / h),
                        x1=clamp(rect.x1 / w),
                        y1=clamp(rect.y1 / h),
                    )
                    out.append(HiddenSpan((page.number or 0) + 1, text, box, reason))
    return out


def _norm(text: str) -> str:
    return " ".join(text.split())


def _covered_share(block: FracBox, span: FracBox) -> float:
    x = max(0.0, min(block.x1, span.x1) - max(block.x0, span.x0))
    y = max(0.0, min(block.y1, span.y1) - max(block.y0, span.y0))
    area = (block.x1 - block.x0) * (block.y1 - block.y0)
    return x * y / area if area > 0 else 0.0


def mark_hidden(parsed: ParsedDocument, spans: list[HiddenSpan]) -> ParsedDocument:
    """Mark the blocks that hold hidden text. A hidden line inside a visible block is cut out of it
    and kept as its own hidden block; text the parser never read becomes a hidden block too, so the
    signal is not lost. Marking twice gives the same document."""
    if not spans:
        return parsed
    blocks = [b.model_copy() for b in parsed.blocks]
    next_seq = max((b.seq for b in blocks), default=-1) + 1

    def add(span: HiddenSpan) -> None:
        nonlocal next_seq
        blocks.append(
            Block(
                page=span.page,
                seq=next_seq,
                kind="hidden_text",
                text=span.text,
                bbox=span.bbox,
                hidden=span.reason,
            )
        )
        next_seq += 1

    for span in spans:
        needle = _norm(span.text)
        on_page = [b for b in blocks if b.page == span.page]
        if any(b.hidden and _norm(b.text) == needle for b in on_page):
            continue
        host = next((b for b in on_page if not b.hidden and needle in _norm(b.text)), None)
        if host is not None:
            rest = _norm(_norm(host.text).replace(needle, " ", 1))
            if re.search(r"\w", rest):
                host.text = rest
                add(span)
            else:
                host.hidden = span.reason
            continue
        overlapped = [
            b for b in on_page if not b.hidden and _covered_share(b.bbox, span.bbox) >= 0.5
        ]
        for b in overlapped:
            b.hidden = span.reason
        if not overlapped:
            add(span)
    return parsed.model_copy(update={"blocks": blocks})
