"""Shared fixtures for the api tests: the app against the test database, a fake arq pool,
demo users with a known password, and a claim in review with one field and one vault value."""

import uuid

import httpx
import pytest
from cryptography.fernet import Fernet

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import Claim, Document, ExtractedField
from claimpilot_core.pii.vault import Vault
from claimpilot_core.settings import get_settings

TEST_DB = "postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5438/claimpilot_test"
KEY = Fernet.generate_key().decode()
PASSWORD = "test-demo-password"


class FakeArq:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, *args):
        self.jobs.append((name, args))


@pytest.fixture
async def client(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAIMPILOT_DATABASE_URL", TEST_DB)
    monkeypatch.setenv("CLAIMPILOT_PII_VAULT_KEY", KEY)
    monkeypatch.setenv("CLAIMPILOT_DEMO_PASSWORD", PASSWORD)
    monkeypatch.setenv("CLAIMPILOT_MCP_TOKEN", "svc-token")
    monkeypatch.setenv("CLAIMPILOT_INTAKE_TOKEN", "intake-token")
    monkeypatch.setenv("CLAIMPILOT_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    from claimpilot_api.auth import ensure_demo_users
    from claimpilot_api.main import app

    async with db_session.session_scope() as s:
        from sqlalchemy import update

        from claimpilot_api.auth import hash_password
        from claimpilot_core.db.models import User

        await ensure_demo_users(s)
        await s.flush()
        await s.execute(
            update(User)
            .where(User.username.in_(["handler.demo", "senior.demo"]))
            .values(password_hash=hash_password(PASSWORD))
        )
    app.state.arq = FakeArq()
    from claimpilot_api import review

    review.FAILED_LOGINS.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()


async def make_claim(status="IN_REVIEW", queue="standard") -> tuple[uuid.UUID, int]:
    async with db_session.session_scope() as s:
        claim = Claim(reference=f"T-{uuid.uuid4().hex[:8]}", status=status, queue=queue)
        s.add(claim)
        await s.flush()
        doc = Document(
            case_id=claim.id,
            filename="inv.pdf",
            mime_type="application/pdf",
            sha256="a" * 64,
            storage_path="x",
            doc_type="medical_invoice",
            page_count=1,
        )
        s.add(doc)
        await s.flush()
        field = ExtractedField(
            case_id=claim.id,
            document_id=doc.id,
            field="patient_name",
            value_raw="<PERSON_1>",
            value_norm="<PERSON_1>",
            method="llm_text",
            grounded=True,
            confidence=0.95,
        )
        s.add(field)
        await Vault(KEY).store(s, claim.id, {"<PERSON_1>": ("PERSON", "Jana Kováčová")})
        await s.flush()
        return claim.id, field.id


async def assess(cid: uuid.UUID) -> None:
    """What the assess step leaves behind: a coverage decision newer than any correction."""
    from claimpilot_core.db.models import CoverageDecision

    async with db_session.session_scope() as s:
        s.add(
            CoverageDecision(
                claim_id=cid,
                item_ref="I1",
                item_description="x",
                coverage="medical",
                verdict="covered",
                clause_ids=[],
                claimed_amount=None,
                claimed_currency=None,
                payout_eur=0,
                deductible_eur=0,
                rationale="",
                confidence=0.9,
            )
        )


async def login(c, user="handler.demo"):
    r = await c.post("/api/auth/login", json={"username": user, "password": PASSWORD})
    assert r.status_code == 200
