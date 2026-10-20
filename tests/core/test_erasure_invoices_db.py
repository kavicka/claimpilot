"""Invoice retention (ADR-016): personal data goes first, the accounting record stays, and the
whole case goes when the accounting period is over."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import (
    AuditLog,
    Case,
    Claim,
    DocBlock,
    DocCell,
    Document,
    ExtractedField,
    Invoice,
    VaultEntry,
)
from claimpilot_core.erasure import (
    erase_case,
    erase_claim,
    erase_invoice_personal_data,
    invoices_due_deletion,
    invoices_due_personal_erasure,
)
from claimpilot_core.retention import InvoiceRetention
from claimpilot_core.settings import get_settings

pytestmark = pytest.mark.db
TEST_DB = "postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5438/claimpilot_test"
POLICY = InvoiceRetention(invoice_years=10, personal_data_days=365)


@pytest.fixture(autouse=True)
def test_database(monkeypatch):
    monkeypatch.setenv("CLAIMPILOT_DATABASE_URL", TEST_DB)
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()


async def make_invoice(
    storage, *, status="EXPORTED", closed_days_ago=0
) -> tuple[uuid.UUID, uuid.UUID]:
    """An exported invoice with a person's name in text, vault, a note, a file and renders."""
    async with db_session.session_scope() as s:
        inv = Invoice(
            reference=f"FA-{uuid.uuid4().hex[:8]}",
            status=status,
            invoice_number="2026-001",
            supplier_ico="12345678",
            total=Decimal("120.00"),
            currency="EUR",
            updated_at=datetime.now(UTC) - timedelta(days=closed_days_ago),
        )
        s.add(inv)
        await s.flush()
        doc = Document(
            case_id=inv.id,
            filename="Faktura Novak Jan.pdf",
            mime_type="application/pdf",
            sha256="x" * 64,
            storage_path=f"invoices/{inv.id}/a.pdf",
            page_count=1,
        )
        s.add(doc)
        await s.flush()
        folder = storage / "invoices" / str(inv.id)
        folder.mkdir(parents=True)
        (folder / "a.pdf").write_bytes("%PDF Ján Novák".encode())
        (folder / "export.xml").write_bytes(b"<Invoice/>")
        (storage / "renders" / str(doc.id)).mkdir(parents=True)
        (storage / "renders" / str(doc.id) / "p1.png").write_bytes(b"png")
        s.add(
            DocBlock(
                document_id=doc.id,
                page=1,
                seq=0,
                kind="text",
                text="Kontakt: Ján Novák",
                text_redacted="Kontakt: <PERSON_1>",
                bbox={},
            )
        )
        s.add(
            DocBlock(
                document_id=doc.id,
                page=1,
                seq=1,
                kind="text",
                text="Never redacted text",
                text_redacted=None,
                bbox={},
            )
        )
        s.add(
            DocCell(
                document_id=doc.id,
                page=1,
                tbl=0,
                item=1,
                line=0,
                col=0,
                header="name",
                text="Ján Novák 0907 123 456",
                text_redacted="<PERSON_1> <PHONE_1>",
                bbox={},
            )
        )
        s.add(
            ExtractedField(
                case_id=inv.id,
                document_id=doc.id,
                field="total",
                value_raw="120.00",
                value_norm="120.00",
                method="llm_text",
            )
        )
        s.add(
            VaultEntry(
                case_id=inv.id, token="<PERSON_1>", entity_type="PERSON", value_encrypted=b"x"
            )
        )
        s.add(AuditLog(case_id=inv.id, action="approve", details={"note": "ask Ján Novák", "x": 1}))
        return inv.id, doc.id


async def count(model, **where) -> int:
    async with db_session.session_scope() as s:
        q = select(func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return await s.scalar(q) or 0


async def test_personal_data_erasure_keeps_the_accounting_record(tmp_path):
    iid, doc_id = await make_invoice(tmp_path)
    async with db_session.session_scope() as s:
        assert await erase_invoice_personal_data(s, iid, tmp_path, reason="client request")

    assert await count(VaultEntry, case_id=iid) == 0
    async with db_session.session_scope() as s:
        blocks = (
            await s.scalars(
                select(DocBlock).where(DocBlock.document_id == doc_id).order_by(DocBlock.seq)
            )
        ).all()
        cell = (await s.scalars(select(DocCell).where(DocCell.document_id == doc_id))).one()
        doc = await s.get(Document, doc_id)
        inv = await s.get(Invoice, iid)
        audit = (await s.scalars(select(AuditLog).where(AuditLog.case_id == iid))).all()
    assert [b.text for b in blocks] == ["Kontakt: <PERSON_1>", ""]
    assert cell.text == "<PERSON_1> <PHONE_1>"
    assert doc is not None and "Novak" not in doc.filename and doc.filename.endswith(".pdf")
    # Files: the upload and its renders are gone, the export stays.
    folder = tmp_path / "invoices" / str(iid)
    assert not (folder / "a.pdf").exists()
    assert (folder / "export.xml").read_bytes() == b"<Invoice/>"
    assert not (tmp_path / "renders" / str(doc_id)).exists()
    # Accounting record: header, fields, status.
    assert inv is not None and inv.status == "EXPORTED" and inv.total == Decimal("120.00")
    assert inv.invoice_number == "2026-001"
    assert await count(ExtractedField, case_id=iid) == 1
    # Audit: the handler's note is gone, the action stays, one line records the erasure.
    by_action = {a.action: a for a in audit}
    assert "Ján" not in str(by_action["approve"].details)
    assert by_action["approve"].details["x"] == 1
    assert by_action["personal_data_erased"].details["reason"] == "client request"
    assert "Ján" not in str(by_action["personal_data_erased"].details)


async def test_personal_data_erasure_does_not_move_the_retention_clock(tmp_path):
    iid, _ = await make_invoice(tmp_path, closed_days_ago=400)
    async with db_session.session_scope() as s:
        before = (await s.get(Case, iid)).updated_at
    async with db_session.session_scope() as s:
        await erase_invoice_personal_data(s, iid, tmp_path, reason="retention")
    async with db_session.session_scope() as s:
        assert (await s.get(Case, iid)).updated_at == before


async def test_erasing_twice_is_harmless(tmp_path):
    iid, _ = await make_invoice(tmp_path)
    for _ in range(2):
        async with db_session.session_scope() as s:
            assert await erase_invoice_personal_data(s, iid, tmp_path, reason="r")
    assert await count(AuditLog, case_id=iid, action="personal_data_erased") == 1


async def test_only_invoices_are_erased_this_way(tmp_path):
    async with db_session.session_scope() as s:
        claim = Claim(reference=f"E-{uuid.uuid4().hex[:8]}", status="SUBMITTED")
        s.add(claim)
        await s.flush()
        cid = claim.id
    async with db_session.session_scope() as s:
        assert not await erase_invoice_personal_data(s, cid, tmp_path, reason="r")
        assert not await erase_invoice_personal_data(s, uuid.uuid4(), tmp_path, reason="r")
        assert await erase_claim(s, cid, tmp_path, reason="cleanup")


async def test_personal_data_selection(tmp_path):
    old_done, _ = await make_invoice(tmp_path, status="EXPORTED", closed_days_ago=400)
    old_rejected, _ = await make_invoice(tmp_path, status="REJECTED", closed_days_ago=400)
    old_abandoned, _ = await make_invoice(tmp_path, status="NEEDS_INFO", closed_days_ago=400)
    old_open, _ = await make_invoice(tmp_path, status="IN_REVIEW", closed_days_ago=400)
    fresh, _ = await make_invoice(tmp_path, status="EXPORTED", closed_days_ago=10)
    erased, _ = await make_invoice(tmp_path, status="EXPORTED", closed_days_ago=400)
    async with db_session.session_scope() as s:
        await erase_invoice_personal_data(s, erased, tmp_path, reason="r")
    async with db_session.session_scope() as s:
        ids = set(await invoices_due_personal_erasure(s, POLICY))
    assert {old_done, old_rejected, old_abandoned} <= ids
    assert not ({old_open, fresh, erased} & ids)


async def test_full_deletion_waits_for_the_end_of_the_accounting_period(tmp_path):
    year = datetime.now(UTC).year
    # Closed in December ten years ago: retention runs to the end of year + 10.
    just_inside, _ = await make_invoice(tmp_path, closed_days_ago=365 * 10 + 5)
    async with db_session.session_scope() as s:
        # Pin the dates: one closed in (year - 11), one in (year - 9).
        await s.execute(
            Case.__table__.update()
            .where(Case.id == just_inside)
            .values(updated_at=datetime(year - 9, 6, 1, tzinfo=UTC))
        )
    due, _ = await make_invoice(tmp_path, closed_days_ago=0)
    async with db_session.session_scope() as s:
        await s.execute(
            Case.__table__.update()
            .where(Case.id == due)
            .values(updated_at=datetime(year - 11, 12, 31, tzinfo=UTC))
        )
    open_old, _ = await make_invoice(tmp_path, status="IN_REVIEW", closed_days_ago=4000)
    async with db_session.session_scope() as s:
        ids = set(await invoices_due_deletion(s, POLICY))
    assert due in ids
    assert just_inside not in ids and open_old not in ids


async def test_full_deletion_removes_rows_and_every_file(tmp_path):
    iid, doc_id = await make_invoice(tmp_path)
    async with db_session.session_scope() as s:
        reference = (await s.get(Case, iid)).reference
        audit_ids = list(await s.scalars(select(AuditLog.id).where(AuditLog.case_id == iid)))
    async with db_session.session_scope() as s:
        assert await erase_case(s, iid, tmp_path, reason="accounting retention ended")
    assert await count(Case, id=iid) == 0
    assert await count(Invoice, id=iid) == 0
    assert await count(Document, case_id=iid) == 0
    assert await count(ExtractedField, case_id=iid) == 0
    assert await count(VaultEntry, case_id=iid) == 0
    assert not (tmp_path / "invoices" / str(iid)).exists()
    assert not (tmp_path / "renders" / str(doc_id)).exists()
    async with db_session.session_scope() as s:
        lines = (await s.scalars(select(AuditLog).where(AuditLog.id.in_(audit_ids)))).all()
        logs = (await s.scalars(select(AuditLog).where(AuditLog.action == "erasure"))).all()
    assert lines and all(a.case_id is None and "Ján" not in str(a.details) for a in lines)
    mine = [a for a in logs if a.details.get("reference") == reference]
    assert len(mine) == 1 and mine[0].details["reason"] == "accounting retention ended"
