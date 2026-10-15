"""Black out personal data on page images before they go to a model outside the machine (Phase 2).

The redactor knows every personal value of the claim (it read the OCR text). A text block that
contains one is covered with a black box on the page image, whole block plus a margin: OCR gives
block positions, not word positions, and a box cut to a guessed word position could leave half a
name readable. The model reads the rest of the page from the image and the personal values from
the redacted text, where they are tokens.

Blocks only cover what the parser read. Docling sometimes files a form, a letterhead or a stamp as a
picture and returns no text for it; the redactor never saw that text, so a name in it would stay
readable (the masking eval caught this on a baggage report and two medical reports). A second,
independent text detector (RapidOCR, detection only, no recognition) finds every line of text on
the page, and any line that no parsed block covers is blacked out too.

`mask_pages` refuses (returns None) when masking cannot be trusted:
- a page has almost no OCR text, so nothing on it could have been found (a photo OCR could not
  read, or handwriting);
- a block holds a personal value but has no usable position;
- the text detector fails.
Handwriting the detector does not see stays visible; docs/adr/010 lists it as a known gap.
The caller then reads the document from its redacted text instead.
"""

import base64
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import Image, ImageDraw

from claimpilot_core.pii.guard import ClaimRedactor, pattern_spans
from claimpilot_core.schemas.parsing import Block, ParsedDocument

MIN_PAGE_CHARS = 40  # below this, OCR did not read the page; nothing on it can be vouched for
MARGIN = 0.006  # of the page size, around each box
COVERED = 0.6  # share of a detected line's area inside one parsed block for it to count as read
BLACK = (0, 0, 0)

Box = tuple[float, float, float, float]  # x0, y0, x1, y1 as fractions, top-left origin
TextFinder = Callable[[Image.Image], list[Box]]


@dataclass
class MaskReport:
    masked_blocks: int = 0
    pages: int = 0
    unread_lines: int = 0
    refused: str | None = None
    boxes: list[tuple[int, Box]] = field(default_factory=list)


def has_personal_data(redactor: ClaimRedactor) -> Callable[[str], bool]:
    """A block holds personal data when it contains a value the claim's redactor knows, in any of
    its forms, or anything the pattern recognizers find (IBAN, birth number, phone, e-mail)."""
    return lambda text: bool(redactor.find(text)) or bool(pattern_spans(text))


@lru_cache(maxsize=1)
def _detector():
    from rapidocr import RapidOCR

    return RapidOCR()


def detect_text_lines(img: Image.Image) -> list[Box]:
    """Every line of text RapidOCR's detector finds on the page, as fractional boxes."""
    out = _detector()(img, use_det=True, use_cls=False, use_rec=False)
    quads = getattr(out, "boxes", None)  # detection only returns TextDetOutput
    if quads is None:
        return []
    w, h = img.size
    return [
        (
            float(q[:, 0].min()) / w,
            float(q[:, 1].min()) / h,
            float(q[:, 0].max()) / w,
            float(q[:, 1].max()) / h,
        )
        for q in quads
    ]


def _covered(line: Box, blocks: list[Block]) -> bool:
    area = (line[2] - line[0]) * (line[3] - line[1])
    if area <= 0:
        return True
    for b in blocks:
        bx = b.bbox
        dx = min(line[2], bx.x1 + MARGIN) - max(line[0], bx.x0 - MARGIN)
        dy = min(line[3], bx.y1 + MARGIN) - max(line[1], bx.y0 - MARGIN)
        if dx > 0 and dy > 0 and dx * dy >= COVERED * area:
            return True
    return False


def _pad(box: Box) -> Box:
    return (
        max(0.0, box[0] - MARGIN),
        max(0.0, box[1] - MARGIN),
        min(1.0, box[2] + MARGIN),
        min(1.0, box[3] + MARGIN),
    )


def _usable(block: Block) -> bool:
    b = block.bbox
    return 0 <= b.x0 < b.x1 <= 1.0001 and 0 <= b.y0 < b.y1 <= 1.0001


def mask_pages(
    images_b64: list[str],
    parsed: ParsedDocument,
    has_personal_data: Callable[[str], bool],
    find_text: TextFinder = detect_text_lines,
) -> tuple[list[str] | None, MaskReport]:
    """Masked copies of the page images, or None with the reason in the report."""
    report = MaskReport(pages=len(images_b64))
    chars = {p.page: 0 for p in parsed.pages}
    for b in parsed.blocks:
        chars[b.page] = chars.get(b.page, 0) + len(b.text.strip())
    for n in range(1, len(images_b64) + 1):
        if chars.get(n, 0) < MIN_PAGE_CHARS:
            report.refused = f"page {n}: OCR read {chars.get(n, 0)} characters"
            return None, report
    flagged = [b for b in parsed.blocks if has_personal_data(b.text)]
    for b in flagged:
        if not _usable(b):
            report.refused = f"page {b.page}: a block with personal data has no position"
            return None, report
    out = []
    for n, image_b64 in enumerate(images_b64, start=1):
        img = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
        try:
            lines = find_text(img)
        except Exception as exc:  # any detector failure means: do not send
            report.refused = f"page {n}: text detection failed ({type(exc).__name__})"
            return None, report
        read = [b for b in parsed.blocks if b.page == n and _usable(b)]
        unread = [line for line in lines if not _covered(line, read)]
        boxes = [_pad((b.bbox.x0, b.bbox.y0, b.bbox.x1, b.bbox.y1)) for b in flagged if b.page == n]
        boxes += [_pad(line) for line in unread]
        report.masked_blocks += sum(b.page == n for b in flagged)
        report.unread_lines += len(unread)
        draw = ImageDraw.Draw(img)
        w, h = img.size
        for box in boxes:
            draw.rectangle([box[0] * w, box[1] * h, box[2] * w, box[3] * h], fill=BLACK)
            report.boxes.append((n, box))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out.append(base64.b64encode(buf.getvalue()).decode())
    return out, report
