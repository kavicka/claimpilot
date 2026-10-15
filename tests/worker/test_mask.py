"""Masking page images before a cloud model sees them."""

import base64
import io

from PIL import Image

from claimpilot_core.pii.guard import ClaimRedactor
from claimpilot_core.schemas.parsing import Block, FracBox, PageInfo, ParsedDocument
from claimpilot_worker.ingest import mask
from claimpilot_worker.ingest.mask import has_personal_data


def mask_pages(images, parsed, detect, lines=()):
    """The masker with a stand-in text detector that finds `lines` on every page."""
    return mask.mask_pages(images, parsed, detect, find_text=lambda _img: list(lines))


def page(color="white") -> str:
    buf = io.BytesIO()
    Image.new("RGB", (200, 300), color).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def pixels(image_b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")


def block(text, x0, y0, x1, y1, page=1, seq=0) -> Block:
    return Block(
        page=page,
        seq=seq,
        kind="text",
        text=text,
        bbox=FracBox(x0=x0, y0=y0, x1=x1, y1=y1),
        ocr=True,
    )


def doc(*blocks, pages=1) -> ParsedDocument:
    return ParsedDocument(
        sha256="x",
        mime_type="application/pdf",
        pages=[PageInfo(page=n, width=1, height=1) for n in range(1, pages + 1)],
        blocks=list(blocks),
    )


def redactor() -> ClaimRedactor:
    return ClaimRedactor.from_mapping({"<PERSON_1>": ("PERSON", "Jana Kováčová")}, ner=None)


LONG = "Fattura n. RE-2026-04417 Totale EUR 279,50 Ospedale Civile Schiavone"


def test_a_block_with_a_known_name_is_blacked_out_and_the_rest_is_kept():
    parsed = doc(
        block(LONG, 0.1, 0.05, 0.9, 0.1, seq=0),
        block("Paziente: Kovacova Jana", 0.1, 0.4, 0.6, 0.45, seq=1),
    )
    masked, report = mask_pages([page()], parsed, has_personal_data(redactor()))
    assert masked is not None and report.masked_blocks == 1
    img = pixels(masked[0])
    assert img.getpixel((70, 127)) == (0, 0, 0)  # inside the name's block (x 0.35, y 0.425)
    assert img.getpixel((100, 22)) == (255, 255, 255)  # the invoice line is untouched


def test_patterns_are_masked_even_when_the_redactor_never_saw_them():
    parsed = doc(block(LONG + " IBAN SK31 1200 0000 1987 4263 7541", 0.1, 0.05, 0.9, 0.1))
    _, report = mask_pages([page()], parsed, has_personal_data(redactor()))
    assert report.masked_blocks == 1


def test_a_page_ocr_could_not_read_is_never_sent():
    parsed = doc(
        block(LONG, 0.1, 0.1, 0.9, 0.2, page=1), block("x", 0.1, 0.1, 0.2, 0.2, page=2), pages=2
    )
    masked, report = mask_pages([page(), page()], parsed, has_personal_data(redactor()))
    assert masked is None
    assert (report.refused or "").startswith("page 2")


def test_personal_data_without_a_position_is_never_sent():
    broken = Block.model_construct(
        page=1,
        seq=1,
        kind="text",
        text="Jana Kováčová",
        bbox=FracBox(x0=0.5, y0=0.5, x1=0.5, y1=0.5),
        ocr=True,
    )
    parsed = doc(block(LONG, 0.1, 0.1, 0.9, 0.2), broken)
    masked, report = mask_pages([page()], parsed, has_personal_data(redactor()))
    assert masked is None and "no position" in (report.refused or "")


def test_a_page_without_personal_data_goes_unmasked():
    masked, report = mask_pages(
        [page()], doc(block(LONG, 0.1, 0.1, 0.9, 0.2)), has_personal_data(redactor())
    )
    assert masked is not None and report.masked_blocks == 0


def test_text_the_parser_never_read_is_blacked_out():
    """Docling can file a letterhead or a form as a picture and return no text for it. The
    detector still sees the line, so it is covered although the redactor never saw its words."""
    parsed = doc(block(LONG, 0.1, 0.05, 0.9, 0.1))
    inside = (0.12, 0.06, 0.5, 0.09)  # a line of the parsed block
    picture = (0.1, 0.4, 0.6, 0.45)  # a line nobody parsed
    masked, report = mask_pages(
        [page()], parsed, has_personal_data(redactor()), lines=[inside, picture]
    )
    assert masked is not None and report.unread_lines == 1 and report.masked_blocks == 0
    img = pixels(masked[0])
    assert img.getpixel((70, 127)) == (0, 0, 0)
    assert img.getpixel((100, 22)) == (255, 255, 255)


def test_a_detector_failure_means_the_images_are_not_sent():
    def broken(_img):
        raise RuntimeError("model file missing")

    masked, report = mask.mask_pages(
        [page()], doc(block(LONG, 0.1, 0.1, 0.9, 0.2)), has_personal_data(redactor()), broken
    )
    assert masked is None and "text detection failed" in (report.refused or "")


def test_the_real_detector_finds_printed_lines():
    from PIL import ImageDraw, ImageFont

    img = Image.new("RGB", (800, 400), "white")
    ImageDraw.Draw(img).text(
        (60, 180), "Patient: Jana Kovacova", fill="black", font=ImageFont.load_default(size=36)
    )
    lines = mask.detect_text_lines(img)
    assert any(x0 < 0.1 and y0 < 0.5 < y1 for x0, y0, _x1, y1 in lines)
