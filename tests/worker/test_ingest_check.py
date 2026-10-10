"""Files a client can send that cannot be read: each gets a reason for the handler and the client."""

import io
import struct
import zlib

import pymupdf
import pytest
from PIL import Image

from claimpilot_worker.ingest.check import MAX_PAGES, problem_of, unreadable_request


def pdf(pages: int = 1, **save) -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Strana {i + 1}")
    return doc.tobytes(**save)


def png(width: int = 60, height: int = 40) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, "PNG")
    return buf.getvalue()


def png_claiming(width: int, height: int) -> bytes:
    """A tiny PNG whose header claims huge dimensions (a decompression bomb's first bytes)."""
    raw = bytearray(png())
    ihdr = struct.pack(">II", width, height) + raw[24:29]
    raw[16:29] = ihdr
    raw[29:33] = struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    return bytes(raw)


ZERO_PAGES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("ok.pdf", pdf(), None),
        ("ok.png", png(), None),
        ("max.pdf", pdf(MAX_PAGES), None),
        ("locked.pdf", pdf(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="1234"), "password"),
        ("long.pdf", pdf(MAX_PAGES + 1), "too_many_pages"),
        ("empty.pdf", ZERO_PAGES, "no_pages"),
        ("junk.pdf", b"%PDF-1.7\n" + b"\x00garbage" * 200, "damaged"),
        ("cut.png", png()[:60], "damaged"),
        ("text.jpg", b"\xff\xd8\xff" + b"not really a jpeg", "damaged"),
        ("bomb.png", png_claiming(20_000, 20_000), "too_large"),
    ],
)
def test_problem_of(tmp_path, name, data, code):
    path = tmp_path / name
    path.write_bytes(data)
    problem = problem_of(path)
    assert (problem.code if problem else None) == code


def test_a_cut_pdf_is_either_repaired_or_reported(tmp_path):
    """MuPDF repairs many truncated PDFs; what it cannot repair must come back as damaged."""
    path = tmp_path / "cut.pdf"
    path.write_bytes(pdf(3)[:400])
    problem = problem_of(path)
    assert problem is None or problem.code in {"damaged", "no_pages"}


def test_request_names_each_file_and_its_problem(tmp_path):
    (tmp_path / "a.pdf").write_bytes(pdf(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x"))
    (tmp_path / "b.png").write_bytes(png()[:60])
    text = unreadable_request(
        {"faktura.pdf": problem_of(tmp_path / "a.pdf"), "foto.png": problem_of(tmp_path / "b.png")}
    )
    assert "„faktura.pdf“ je chránený heslom" in text
    assert "„foto.png“ je poškodený alebo to nie je obrázok" in text
    assert "Vážená pani / Vážený pán" in text


def test_a_cut_image_is_damaged_even_when_another_library_allows_truncated_images(tmp_path):
    from PIL import ImageFile

    path = tmp_path / "cut.png"
    path.write_bytes(png()[:60])
    before, ImageFile.LOAD_TRUNCATED_IMAGES = ImageFile.LOAD_TRUNCATED_IMAGES, True  # as WeasyPrint
    try:
        assert problem_of(path).code == "damaged"
        assert ImageFile.LOAD_TRUNCATED_IMAGES is True  # left as it was found
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = before
