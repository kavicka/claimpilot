"""The Textract OCR adapter against botocore's Stubber: the real client, no AWS call."""

from pathlib import Path

import boto3
import pymupdf
from botocore.stub import ANY, Stubber
from PIL import Image

from claimpilot_worker.ingest.textract import TextractReader, is_scan


def line(text: str, left: float, top: float, width: float, height: float) -> dict:
    return {
        "BlockType": "LINE",
        "Text": text,
        "Confidence": 99.1,
        "Geometry": {
            "BoundingBox": {"Left": left, "Top": top, "Width": width, "Height": height},
            "Polygon": [],
        },
    }


def stubbed(*responses):
    client = boto3.client(
        "textract",
        region_name="eu-central-1",
        aws_access_key_id="AKIDEXAMPLE",
        aws_secret_access_key="test-only",
    )
    stub = Stubber(client)
    for blocks in responses:
        stub.add_response(
            "detect_document_text",
            {"DocumentMetadata": {"Pages": 1}, "Blocks": blocks},
            {"Document": {"Bytes": ANY}},
        )
    stub.activate()
    return client, stub


def scanned_pdf(path: Path, pages: int) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_image(
            page.rect, pixmap=pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8))
        )
    doc.save(path)
    return path


def test_lines_become_blocks_with_their_page_and_box(tmp_path):
    client, stub = stubbed(
        [
            {"BlockType": "PAGE", "Geometry": {"BoundingBox": {}}},
            line("Fattura n. RE-2026-04417", 0.1, 0.05, 0.4, 0.02),
            line("Paziente:  Jana  Kováčová", 0.1, 0.30, 0.35, 0.02),
            {"BlockType": "WORD", "Text": "Fattura"},
        ],
        [line("Totale EUR 279,50", 0.55, 0.9, 0.3, 0.02)],
    )
    parsed = TextractReader("eu-central-1", client=client).parse(scanned_pdf(tmp_path / "s.pdf", 2))
    stub.assert_no_pending_responses()
    assert [(b.page, b.seq, b.text) for b in parsed.blocks] == [
        (1, 0, "Fattura n. RE-2026-04417"),
        (1, 1, "Paziente: Jana Kováčová"),
        (2, 2, "Totale EUR 279,50"),
    ]
    box = parsed.blocks[2].bbox
    assert (box.x0, box.y0, round(box.x1, 6), round(box.y1, 6)) == (0.55, 0.9, 0.85, 0.92)
    assert all(b.ocr for b in parsed.blocks) and len(parsed.pages) == 2


def test_a_photo_is_one_page(tmp_path):
    photo = tmp_path / "receipt.jpg"
    Image.new("RGB", (300, 500), "white").save(photo)
    client, _ = stubbed([line("Ljekarna Dubrovnik", 0.2, 0.1, 0.5, 0.03)])
    parsed = TextractReader("eu-central-1", client=client).parse(photo)
    assert parsed.mime_type == "image/jpeg"
    assert [(p.page, p.width, p.height) for p in parsed.pages] == [(1, 300, 500)]


def test_only_files_without_a_text_layer_count_as_scans(tmp_path):
    digital = tmp_path / "invoice.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Rechnung")
    doc.save(digital)
    assert not is_scan(digital)
    assert is_scan(scanned_pdf(tmp_path / "scan.pdf", 1))
    assert is_scan(tmp_path / "photo.png")


def test_the_parser_sends_scans_to_textract_only_when_configured(tmp_path, monkeypatch):
    from claimpilot_core.settings import get_settings
    from claimpilot_worker.ingest import parser, textract

    photo = tmp_path / "receipt.jpg"
    Image.new("RGB", (300, 500), "white").save(photo)
    read = []
    monkeypatch.setattr(
        textract.TextractReader, "parse", lambda self, path: read.append(path) or "textract"
    )
    monkeypatch.setattr(textract.TextractReader, "__init__", lambda self, region: None)
    monkeypatch.setattr(parser, "converter", lambda: (_ for _ in ()).throw(AssertionError))
    settings = get_settings().model_copy(update={"ocr_engine": "textract"})
    monkeypatch.setattr(parser, "get_settings", lambda: settings)
    assert parser.parse(photo) == "textract" and read == [photo]
