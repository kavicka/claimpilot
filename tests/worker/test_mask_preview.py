"""Masked page renders for the review UI's Masked view."""

import base64
import json

from PIL import Image
from test_mask import LONG, block, doc, page, redactor

from claimpilot_worker.ingest.mask import has_personal_data
from claimpilot_worker.ingest.mask_preview import write_masked_renders


def renders(tmp_path, pages=1):
    for n in range(1, pages + 1):
        (tmp_path / f"p{n}.png").write_bytes(base64.b64decode(page()))
    return tmp_path


def no_lines(_img):
    return []


def test_masked_pages_and_manifest_are_written_next_to_the_renders(tmp_path):
    parsed = doc(
        block(LONG, 0.1, 0.05, 0.9, 0.1, seq=0),
        block("Paziente: Kovacova Jana", 0.1, 0.4, 0.6, 0.45, seq=1),
    )
    report = write_masked_renders(
        renders(tmp_path), parsed, has_personal_data(redactor()), find_text=no_lines
    )
    assert report is not None and report.masked_blocks == 1
    with Image.open(tmp_path / "m1.png") as img:
        assert img.convert("RGB").getpixel((70, 127)) == (0, 0, 0)
    with Image.open(tmp_path / "p1.png") as img:
        assert img.convert("RGB").getpixel((70, 127)) == (255, 255, 255)  # original untouched
    manifest = json.loads((tmp_path / "mask.json").read_text())
    assert manifest == {"pages": 1, "masked_blocks": 1, "unread_lines": 0, "refused": None}


def test_a_refusal_removes_old_masked_pages_and_records_the_reason(tmp_path):
    renders(tmp_path)
    (tmp_path / "m1.png").write_bytes(b"stale")
    parsed = doc(block("short", 0.1, 0.1, 0.2, 0.2))  # too little OCR text to vouch for the page
    report = write_masked_renders(
        tmp_path, parsed, has_personal_data(redactor()), find_text=no_lines
    )
    assert report is not None and report.refused
    assert not (tmp_path / "m1.png").exists()
    assert json.loads((tmp_path / "mask.json").read_text())["refused"] == report.refused


def test_no_renders_means_nothing_is_written(tmp_path):
    report = write_masked_renders(
        tmp_path, doc(block(LONG, 0.1, 0.05, 0.9, 0.1)), has_personal_data(redactor())
    )
    assert report is None
    assert list(tmp_path.iterdir()) == []
