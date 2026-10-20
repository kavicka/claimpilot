"""Erasure on request for invoices: senior only, only once the invoice is closed."""

import uuid

import pytest
from apitools import login
from sqlalchemy import select

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import AuditLog, DocBlock, Document, Invoice, VaultEntry

pytestmark = pytest.mark.db


async def make_invoice(tmp_path, status: str) -> tuple[uuid.UUID, uuid.UUID]:
    async with db_session.session_scope() as s:
        inv = Invoice(reference=f"R-{uuid.uuid4().hex[:8]}", status=status)
        s.add(inv)
        await s.flush()
        doc = Document(
            case_id=inv.id,
            filename="Novak.pdf",
            mime_type="application/pdf",
            sha256="z" * 64,
            storage_path=f"invoices/{inv.id}/a.pdf",
        )
        s.add(doc)
        await s.flush()
        (tmp_path / "invoices" / str(inv.id)).mkdir(parents=True)
        (tmp_path / "invoices" / str(inv.id) / "a.pdf").write_bytes(b"%PDF")
        s.add(
            DocBlock(
                document_id=doc.id,
                page=1,
                seq=0,
                kind="text",
                text="Ján Novák",
                text_redacted="<PERSON_1>",
                bbox={},
            )
        )
        s.add(
            VaultEntry(
                case_id=inv.id, token="<PERSON_1>", entity_type="PERSON", value_encrypted=b"x"
            )
        )
        return inv.id, doc.id


async def erase(client, iid, reason="client asked"):
    return await client.request(
        "DELETE", f"/api/review/invoices/{iid}/personal-data", json={"reason": reason}
    )


async def test_senior_erases_personal_data_of_a_closed_invoice(client, tmp_path):
    iid, doc_id = await make_invoice(tmp_path, "EXPORTED")
    await login(client, "senior.demo")
    r = await erase(client, iid)
    assert r.status_code == 200 and r.json() == {"erased": True}
    async with db_session.session_scope() as s:
        assert await s.get(Invoice, iid) is not None
        assert (await s.scalars(select(VaultEntry).where(VaultEntry.case_id == iid))).all() == []
        assert (
            await s.scalars(select(DocBlock).where(DocBlock.document_id == doc_id))
        ).one().text == "<PERSON_1>"
        audit = (await s.scalars(select(AuditLog).where(AuditLog.case_id == iid))).all()
        assert (await s.get(Document, doc_id)).filename == "erased.pdf"
    assert [a.action for a in audit] == ["personal_data_erased"]
    assert audit[0].user_id is not None
    assert not (tmp_path / "invoices" / str(iid) / "a.pdf").exists()


async def test_a_handler_cannot_erase(client, tmp_path):
    iid, _ = await make_invoice(tmp_path, "EXPORTED")
    await login(client, "handler.demo")
    assert (await erase(client, iid)).status_code == 403
    assert (tmp_path / "invoices" / str(iid) / "a.pdf").exists()


async def test_an_invoice_in_review_cannot_be_erased(client, tmp_path):
    iid, _ = await make_invoice(tmp_path, "IN_REVIEW")
    await login(client, "senior.demo")
    assert (await erase(client, iid)).status_code == 409
    assert (tmp_path / "invoices" / str(iid) / "a.pdf").exists()


async def test_unknown_invoice_and_claims_are_not_found(client):
    from apitools import make_claim

    await login(client, "senior.demo")
    assert (await erase(client, uuid.uuid4())).status_code == 404
    cid, _ = await make_claim()
    assert (await erase(client, cid)).status_code == 404  # claims are erased whole, elsewhere


async def test_a_reason_is_required(client, tmp_path):
    iid, _ = await make_invoice(tmp_path, "EXPORTED")
    await login(client, "senior.demo")
    assert (await erase(client, iid, reason="")).status_code == 422
