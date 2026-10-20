"""Intake limits: upload size, rate per minute, no orphan files, configurable reference prefix."""

import pytest
from apitools import login
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_uploads_db import INTAKE, pdf_bytes, stored, upload

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import Claim
from claimpilot_core.settings import get_settings

pytestmark = pytest.mark.db


def configure(monkeypatch, **env: str) -> None:
    for key, value in env.items():
        monkeypatch.setenv(f"CLAIMPILOT_{key.upper()}", value)
    get_settings.cache_clear()


async def upload_invoice(client, headers=INTAKE):
    return await client.post(
        "/api/invoices", files={"file": ("f.pdf", pdf_bytes(), "application/pdf")}, headers=headers
    )


async def test_upload_size_limit_comes_from_settings(client, tmp_path, monkeypatch):
    configure(monkeypatch, max_upload_mb="1")
    big = b"%PDF-1.7\n" + b"0" * (1024 * 1024)
    r = await upload(client, ("huge.pdf", big))
    assert r.status_code == 413 and "1 MB" in r.json()["detail"]
    r = await client.post(
        "/api/invoices", files={"file": ("huge.pdf", big, "application/pdf")}, headers=INTAKE
    )
    assert r.status_code == 413
    assert stored(tmp_path) == []
    assert (await upload(client, ("ok.pdf", pdf_bytes()))).status_code == 201


async def test_a_declared_oversize_body_is_refused_before_it_is_read(client, tmp_path, monkeypatch):
    configure(monkeypatch, max_upload_mb="1")
    body = b"%PDF-1.7\n" + b"0" * (5 * 1024 * 1024)  # 5x the limit: over file limit plus slack
    r = await client.post(
        "/api/invoices", files={"file": ("huge.pdf", body, "application/pdf")}, headers=INTAKE
    )
    assert r.status_code == 413 and "1 MB" in r.json()["detail"]
    assert stored(tmp_path) == []


async def test_default_upload_limit_is_25_mb(client):
    assert get_settings().max_upload_mb == 25


async def test_rate_limit_answers_429_with_retry_after(client, monkeypatch):
    configure(monkeypatch, intake_rate_per_min="3")
    assert [(await upload_invoice(client)).status_code for _ in range(3)] == [201, 201, 201]
    r = await upload_invoice(client)
    assert r.status_code == 429
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    # claims share the budget of the same token
    assert (await upload(client, ("a.pdf", pdf_bytes()))).status_code == 429


async def test_rate_limit_is_per_intake_identity(client, monkeypatch):
    configure(monkeypatch, intake_rate_per_min="2")
    for _ in range(2):
        assert (await upload_invoice(client)).status_code == 201
    assert (await upload_invoice(client)).status_code == 429
    await login(client)  # a handler has a budget of their own
    assert (await upload_invoice(client, headers={})).status_code == 201


async def test_rate_limit_can_be_switched_off(client, monkeypatch):
    configure(monkeypatch, intake_rate_per_min="0")
    for _ in range(5):
        assert (await upload_invoice(client)).status_code == 201


async def test_a_failed_commit_leaves_no_file_and_no_row(client, tmp_path, monkeypatch):
    async def boom(self):
        raise RuntimeError("database went away")

    monkeypatch.setattr(AsyncSession, "commit", boom)
    with pytest.raises(RuntimeError, match="database went away"):
        await upload(client, ("a.pdf", pdf_bytes()), ("b.pdf", pdf_bytes()))
    with pytest.raises(RuntimeError, match="database went away"):
        await upload_invoice(client)
    assert stored(tmp_path) == []
    for kind in ("claims", "invoices"):  # the case folders went too
        assert not (tmp_path / kind).exists() or list((tmp_path / kind).iterdir()) == []


async def test_reference_prefix_is_configurable(client, monkeypatch):
    configure(monkeypatch, invoice_reference_prefix="RE-2027-", claim_reference_prefix="SU-2027-")
    invoice = (await upload_invoice(client)).json()
    claim = (await upload(client, ("a.pdf", pdf_bytes()))).json()
    assert invoice["reference"].startswith("RE-2027-") and len(invoice["reference"]) == 14
    assert claim["reference"].startswith("SU-2027-")
    async with db_session.session_scope() as s:
        assert (await s.scalars(select(Claim).where(Claim.reference == claim["reference"]))).one()


async def test_the_default_prefixes_are_unchanged(client):
    assert (await upload_invoice(client)).json()["reference"].startswith("FA-2026-")
    assert (await upload(client, ("a.pdf", pdf_bytes()))).json()["reference"].startswith("CP-2026-")
