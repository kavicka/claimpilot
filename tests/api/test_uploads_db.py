"""Uploads that a client portal could send: wrong types, empty, oversized, renamed, many files."""

import asyncio
import io

import pymupdf
import pytest
from PIL import Image
from sqlalchemy import select

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import Claim, Document

pytestmark = pytest.mark.db
INTAKE = {"X-Intake-Token": "intake-token"}


def pdf_bytes() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Faktúra")
    return doc.tobytes()


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, "PNG")
    return buf.getvalue()


async def upload(client, *files, **form):
    return await client.post(
        "/api/claims", files=[("files", f) for f in files], data=form, headers=INTAKE
    )


def stored(tmp_path) -> list:
    return [p for p in tmp_path.rglob("*") if p.is_file()]


@pytest.mark.parametrize(
    ("name", "data", "status", "message"),
    [
        ("scan.heic", b"\x00\x00\x00\x18ftypheic", 415, "export them as JPG"),
        ("letter.docx", b"PK\x03\x04", 415, "save them as PDF"),
        ("invoice.exe", b"MZ", 415, "only PDF, JPG and PNG"),
        ("empty.pdf", b"", 422, "empty"),
        ("photo.pdf", None, 415, "not a PDF"),  # a PNG renamed to .pdf
        ("page.html.pdf", b"<html><script>alert(1)</script></html>", 415, "not a PDF"),
        ("receipt.jpg", None, 415, "not a JPG"),  # a PNG renamed to .jpg
    ],
)
async def test_bad_files_are_rejected_and_nothing_is_stored(
    client, tmp_path, name, data, status, message
):
    data = png_bytes() if data is None else data
    r = await upload(client, ("good.pdf", pdf_bytes()), (name, data))
    assert r.status_code == status
    assert message in r.json()["detail"]
    assert stored(tmp_path) == []  # the good file in the same upload was not kept either


async def test_oversized_file(client, tmp_path):
    big = b"%PDF-1.7\n" + b"0" * (20 * 1024 * 1024)
    r = await upload(client, ("huge.pdf", big))
    assert r.status_code == 413
    assert stored(tmp_path) == []


async def test_too_many_files(client):
    r = await upload(client, *[(f"p{i}.pdf", pdf_bytes()) for i in range(21)])
    assert r.status_code == 422


async def test_overlong_scenario_id(client):
    r = await upload(client, ("a.pdf", pdf_bytes()), scenario_id="x" * 65)
    assert r.status_code == 422


async def test_filename_is_cleaned_not_trusted(client, tmp_path):
    long = "a" * 300 + ".pdf"
    r = await upload(
        client,
        ("../../etc/passwd.pdf", pdf_bytes()),
        ("C:\\Users\\jana\\faktura.pdf", pdf_bytes()),
        (long, pdf_bytes()),
        ("bad\x00name\n.pdf", pdf_bytes()),
    )
    assert r.status_code == 201
    async with db_session.session_scope() as s:
        names = (
            await s.scalars(select(Document.filename).where(Document.case_id == r.json()["id"]))
        ).all()
    # httpx percent-encodes control characters in multipart names, so they arrive as text
    assert sorted(names) == sorted(
        ["passwd.pdf", "faktura.pdf", "a" * 196 + ".pdf", "bad%00name%0A.pdf"]
    )
    # Files are stored under generated names inside the claim's folder, whatever was uploaded.
    assert all(p.parent.name == r.json()["id"] for p in stored(tmp_path))


async def test_concurrent_uploads_get_distinct_references(client):
    rs = await asyncio.gather(*[upload(client, ("a.pdf", pdf_bytes())) for _ in range(6)])
    assert {r.status_code for r in rs} == {201}
    refs = [r.json()["reference"] for r in rs]
    assert len(set(refs)) == 6


async def test_reference_is_not_reused_after_an_erasure(client):
    from apitools import login

    first = (await upload(client, ("a.pdf", pdf_bytes()))).json()
    await login(client, "senior.demo")
    await client.request("DELETE", f"/api/review/claims/{first['id']}", json={"reason": "test"})
    second = (await upload(client, ("a.pdf", pdf_bytes()))).json()
    assert second["reference"] != first["reference"]
    async with db_session.session_scope() as s:
        assert await s.get(Claim, first["id"]) is None


def test_safe_filename_drops_directories_and_control_characters():
    from claimpilot_api.main import safe_filename

    assert safe_filename("../../x/\x00evil\n.pdf", ".pdf") == "evil.pdf"
    assert safe_filename("C:\\temp\\scan.png", ".png") == "scan.png"
    assert safe_filename("\x01\x02", ".pdf") == "document.pdf"
    assert safe_filename(None, ".jpg") == "document.jpg"
