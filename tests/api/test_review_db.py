"""Review API against the test database: auth, re-hydration, roles, actions, corrections, erasure."""

import uuid

import httpx
import pytest
from cryptography.fernet import Fernet

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import AuditLog, Claim, Document, ExtractedField, VaultEntry
from claimpilot_core.pii.vault import Vault
from claimpilot_core.settings import get_settings

pytestmark = pytest.mark.db
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
            claim_id=claim.id,
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
            claim_id=claim.id,
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


async def test_review_needs_login(client):
    assert (await client.get("/api/review/claims")).status_code == 401
    r = await client.post("/api/auth/login", json={"username": "handler.demo", "password": "wrong"})
    assert r.status_code == 401


async def test_handler_sees_real_values(client):
    cid, _ = await make_claim()
    await login(client)
    detail = (await client.get(f"/api/review/claims/{cid}")).json()
    assert detail["insured"] == "Jana Kováčová"
    assert detail["documents"][0]["fields"][0]["value"] == "Jana Kováčová"


async def test_agent_sees_tokens_and_cannot_act(client):
    cid, fid = await make_claim()
    headers = {"X-Service-Token": "svc-token"}
    detail = (await client.get(f"/api/review/claims/{cid}", headers=headers)).json()
    assert detail["documents"][0]["fields"][0]["value"] == "<PERSON_1>"
    assert "Kováčová" not in str(detail)
    assert (
        await client.post(f"/api/review/claims/{cid}/actions/approve", json={}, headers=headers)
    ).status_code == 403
    assert (
        await client.patch(f"/api/review/fields/{fid}", json={"value": "x"}, headers=headers)
    ).status_code == 403
    assert (
        await client.get("/api/review/claims", headers={"X-Service-Token": "wrong"})
    ).status_code == 401


async def test_approve_enqueues_submission_and_sets_straight_through(client):
    cid, _ = await make_claim()
    await login(client)
    r = await client.post(f"/api/review/claims/{cid}/actions/approve", json={"note": "ok"})
    assert r.json()["status"] == "APPROVED"
    from claimpilot_api.main import app

    assert ("advance", (str(cid),)) in app.state.arq.jobs
    async with db_session.session_scope() as s:
        assert (await s.get(Claim, cid)).straight_through is True


async def test_senior_queue_needs_a_senior(client):
    cid, _ = await make_claim(queue="senior")
    await login(client, "handler.demo")
    assert (
        await client.post(f"/api/review/claims/{cid}/actions/approve", json={})
    ).status_code == 403
    await login(client, "senior.demo")
    assert (await client.post(f"/api/review/claims/{cid}/actions/approve", json={})).json()[
        "status"
    ] == "APPROVED"


async def test_actions_follow_the_state_machine(client):
    cid, _ = await make_claim(status="EXTRACTED")
    await login(client)
    assert (
        await client.post(f"/api/review/claims/{cid}/actions/approve", json={})
    ).status_code == 409


async def test_correction_keeps_tokens_and_marks_the_field(client):
    cid, fid = await make_claim()
    await login(client)
    r = await client.patch(f"/api/review/fields/{fid}", json={"value": "Jana Kováčová"})
    assert r.json()["value"] == "Jana Kováčová"
    async with db_session.session_scope() as s:
        f = await s.get(ExtractedField, fid)
        assert (
            f.value_raw == "<PERSON_1>"
        )  # the vault already holds this value: stored as its token
        assert f.corrected is True
    await assess(cid)
    r = await client.post(f"/api/review/claims/{cid}/actions/approve", json={})
    assert r.json()["status"] == "APPROVED"
    async with db_session.session_scope() as s:
        assert (await s.get(Claim, cid)).straight_through is False


async def test_only_seniors_erase(client):
    cid, _ = await make_claim()
    await login(client, "handler.demo")
    assert (
        await client.request("DELETE", f"/api/review/claims/{cid}", json={"reason": "x"})
    ).status_code == 403
    await login(client, "senior.demo")
    assert (
        await client.request("DELETE", f"/api/review/claims/{cid}", json={"reason": "client asked"})
    ).json() == {"erased": True}
    async with db_session.session_scope() as s:
        assert await s.get(Claim, cid) is None
        from sqlalchemy import func, select

        assert (
            await s.scalar(
                select(func.count()).select_from(VaultEntry).where(VaultEntry.claim_id == cid)
            )
            == 0
        )


async def test_uploads_and_lists_need_a_token_or_login(client):
    files = [("files", ("a.pdf", b"%PDF-1.4 test"))]
    assert (await client.post("/api/claims", files=files)).status_code == 401
    assert (await client.get("/api/claims")).status_code == 401
    r = await client.post("/api/claims", files=files, headers={"X-Intake-Token": "intake-token"})
    assert r.status_code == 201
    assert (await client.get(f"/api/claims/{r.json()['id']}/steps")).status_code == 401


async def test_agent_cannot_load_page_images(client):
    r = await client.get(
        f"/api/review/documents/{uuid.uuid4()}/pages/1", headers={"X-Service-Token": "svc-token"}
    )
    assert r.status_code == 403


async def test_new_personal_value_goes_to_the_vault_not_the_table(client):
    cid, fid = await make_claim()
    await login(client)
    r = await client.patch(f"/api/review/fields/{fid}", json={"value": "Jana Nováková"})
    assert r.json()["value"] == "Jana Nováková"
    async with db_session.session_scope() as s:
        f = await s.get(ExtractedField, fid)
        assert f.value_raw == "<PERSON_2>"
        assert (await Vault(KEY).load(s, cid))["<PERSON_2>"] == "Jana Nováková"


async def test_fraud_review_needs_a_senior_for_every_decision(client):
    cid, _ = await make_claim(queue="fraud_review")
    await login(client, "handler.demo")
    for action in ("approve", "reject", "request-info"):
        r = await client.post(f"/api/review/claims/{cid}/actions/{action}", json={})
        assert r.status_code == 403


async def test_erasure_drops_handler_notes_from_the_audit_log(client):
    cid, _ = await make_claim()
    await login(client, "senior.demo")
    await client.post(
        f"/api/review/claims/{cid}/actions/request-info", json={"note": "called Jana Kováčová"}
    )
    await client.request("DELETE", f"/api/review/claims/{cid}", json={"reason": "client asked"})
    async with db_session.session_scope() as s:
        from sqlalchemy import select

        details = (await s.scalars(select(AuditLog.details))).all()
        assert not any("Kováčová" in str(d) for d in details)


async def test_corrections_must_be_reassessed_before_approval(client):
    cid, fid = await make_claim()
    await login(client)
    await client.patch(f"/api/review/fields/{fid}", json={"value": "Jana Nováková"})
    detail = (await client.get(f"/api/review/claims/{cid}")).json()
    assert detail["needs_reassessment"] is True
    r = await client.post(f"/api/review/claims/{cid}/actions/approve", json={})
    assert r.status_code == 409
    r = await client.post(f"/api/review/claims/{cid}/actions/reassess", json={})
    assert r.json()["status"] == "EXTRACTED"
    from claimpilot_api.main import app

    assert ("advance", (str(cid),)) in app.state.arq.jobs
