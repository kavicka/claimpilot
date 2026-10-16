"""Erasure removes a claim end to end: rows, vault entries, stored files and page renders.
The audit log keeps a line that the claim existed and was erased, without its data."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import (
    AuditLog,
    Claim,
    DocBlock,
    Document,
    ExtractedField,
    VaultEntry,
)
from claimpilot_core.erasure import erase_claim, expired_claims
from claimpilot_core.settings import get_settings

pytestmark = pytest.mark.db
TEST_DB = "postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5438/claimpilot_test"


@pytest.fixture(autouse=True)
def test_database(monkeypatch):
    monkeypatch.setenv("CLAIMPILOT_DATABASE_URL", TEST_DB)
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()


async def make_claim(storage, *, status="SUBMITTED", age_days=0) -> uuid.UUID:
    async with db_session.session_scope() as s:
        claim = Claim(
            reference=f"E-{uuid.uuid4().hex[:8]}",
            status=status,
            created_at=datetime.now(UTC) - timedelta(days=age_days),
        )
        s.add(claim)
        await s.flush()
        doc = Document(
            case_id=claim.id,
            filename="a.pdf",
            mime_type="application/pdf",
            sha256="x" * 64,
            storage_path=f"claims/{claim.id}/a.pdf",
        )
        s.add(doc)
        await s.flush()
        (storage / "claims" / str(claim.id)).mkdir(parents=True)
        (storage / "claims" / str(claim.id) / "a.pdf").write_bytes(b"%PDF")
        (storage / "renders" / str(doc.id)).mkdir(parents=True)
        (storage / "renders" / str(doc.id) / "p1.png").write_bytes(b"png")
        s.add(DocBlock(document_id=doc.id, page=1, seq=0, kind="text", text="Jana", bbox={}))
        s.add(
            ExtractedField(
                case_id=claim.id,
                document_id=doc.id,
                field="patient_name",
                value_raw="<PERSON_1>",
                method="llm_text",
            )
        )
        s.add(
            VaultEntry(
                case_id=claim.id, token="<PERSON_1>", entity_type="PERSON", value_encrypted=b"x"
            )
        )
        return claim.id


async def count(model, **where) -> int:
    async with db_session.session_scope() as s:
        q = select(func.count()).select_from(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return await s.scalar(q) or 0


async def test_erase_removes_rows_vault_and_files(tmp_path):
    cid = await make_claim(tmp_path)
    async with db_session.session_scope() as s:
        await erase_claim(s, cid, tmp_path, reason="client request")
    assert await count(Claim, id=cid) == 0
    assert await count(VaultEntry, case_id=cid) == 0
    assert await count(ExtractedField, case_id=cid) == 0
    assert not (tmp_path / "claims" / str(cid)).exists()
    assert not any((tmp_path / "renders").iterdir())
    async with db_session.session_scope() as s:
        log = (
            await s.scalars(
                select(AuditLog).where(AuditLog.action == "erasure").order_by(AuditLog.id.desc())
            )
        ).first()
    assert log is not None and log.case_id is None and log.details["reason"] == "client request"
    assert "Jana" not in str(log.details)


async def test_retention_selects_only_old_finished_claims(tmp_path):
    old_done = await make_claim(tmp_path, status="SUBMITTED", age_days=400)
    old_open = await make_claim(tmp_path, status="IN_REVIEW", age_days=400)
    new_done = await make_claim(tmp_path, status="REJECTED", age_days=10)
    async with db_session.session_scope() as s:
        ids = set(await expired_claims(s, retention_days=365))
    assert old_done in ids
    assert old_open not in ids and new_done not in ids
