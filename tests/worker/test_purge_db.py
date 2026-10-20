"""The daily purge job handles claims and invoices (ADR-016). The selection functions are
replaced by the ids of this test: the shared test database holds other tests' old rows."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from claimpilot_core import erasure
from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import Case, Claim, DocBlock, Document, Invoice, VaultEntry
from claimpilot_core.settings import get_settings
from claimpilot_worker.main import purge

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


async def make_case(storage, model, folder: str) -> tuple[uuid.UUID, uuid.UUID]:
    async with db_session.session_scope() as s:
        case = model(
            reference=f"P-{uuid.uuid4().hex[:8]}",
            status="SUBMITTED" if model is Claim else "EXPORTED",
            created_at=datetime.now(UTC) - timedelta(days=4000),
        )
        s.add(case)
        await s.flush()
        doc = Document(
            case_id=case.id,
            filename="a.pdf",
            mime_type="application/pdf",
            sha256="y" * 64,
            storage_path=f"{folder}/{case.id}/a.pdf",
        )
        s.add(doc)
        await s.flush()
        (storage / folder / str(case.id)).mkdir(parents=True)
        (storage / folder / str(case.id) / "a.pdf").write_bytes(b"%PDF")
        s.add(DocBlock(document_id=doc.id, page=1, seq=0, kind="text", text="Jana", bbox={}))
        s.add(
            VaultEntry(
                case_id=case.id, token="<PERSON_1>", entity_type="PERSON", value_encrypted=b"x"
            )
        )
        return case.id, doc.id


async def test_purge_erases_claims_strips_invoices_and_deletes_old_invoices(tmp_path, monkeypatch):
    claim, _ = await make_case(tmp_path, Claim, "claims")
    young_invoice, young_doc = await make_case(tmp_path, Invoice, "invoices")
    old_invoice, _ = await make_case(tmp_path, Invoice, "invoices")

    async def claims(_s, *, retention_days):
        return [claim]

    async def personal(_s, _policy, **_kw):
        return [young_invoice, old_invoice]  # the old one is due for deletion as well

    async def deletions(_s, _policy, **_kw):
        return [old_invoice]

    monkeypatch.setattr(erasure, "expired_claims", claims)
    monkeypatch.setattr(erasure, "invoices_due_personal_erasure", personal)
    monkeypatch.setattr(erasure, "invoices_due_deletion", deletions)

    settings = get_settings().model_copy(update={"storage_dir": tmp_path})
    assert await purge({"settings": settings}) == 3

    async with db_session.session_scope() as s:
        assert await s.get(Case, claim) is None
        assert await s.get(Case, old_invoice) is None
        kept = await s.get(Invoice, young_invoice)
        assert kept is not None  # the accounting record stays
        block = (await s.scalars(select(DocBlock).where(DocBlock.document_id == young_doc))).one()
        assert block.text == ""
    assert not (tmp_path / "claims" / str(claim)).exists()
    assert not (tmp_path / "invoices" / str(old_invoice)).exists()
    assert not (tmp_path / "invoices" / str(young_invoice) / "a.pdf").exists()


async def test_one_failing_case_does_not_hold_back_the_others(tmp_path, monkeypatch):
    bad, _ = await make_case(tmp_path, Claim, "claims")
    good, _ = await make_case(tmp_path, Claim, "claims")

    async def claims(_s, *, retention_days):
        return [bad, good]

    async def none(_s, _policy, **_kw):
        return []

    real = erasure.erase_claim

    async def flaky(session, cid, *a, **kw):
        if cid == bad:
            raise RuntimeError("disk is read-only")
        return await real(session, cid, *a, **kw)

    monkeypatch.setattr(erasure, "expired_claims", claims)
    monkeypatch.setattr(erasure, "invoices_due_personal_erasure", none)
    monkeypatch.setattr(erasure, "invoices_due_deletion", none)
    monkeypatch.setattr(erasure, "erase_claim", flaky)

    settings = get_settings().model_copy(update={"storage_dir": tmp_path})
    assert await purge({"settings": settings}) == 1
    async with db_session.session_scope() as s:
        assert await s.get(Case, good) is None
        assert await s.get(Case, bad) is not None
