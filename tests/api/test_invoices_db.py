"""Invoice review API against the test database: intake, queue, detail, corrections, actions."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apitools import KEY, login

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import (
    AuditLog,
    DocCell,
    Document,
    ExtractedField,
    Invoice,
    PipelineStepRun,
)
from claimpilot_core.pii.vault import Vault

pytestmark = pytest.mark.db
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


async def make_invoice(queue="standard", status="IN_REVIEW") -> tuple[uuid.UUID, dict[str, int]]:
    async with db_session.session_scope() as s:
        inv = Invoice(
            reference=f"T-{uuid.uuid4().hex[:8]}",
            status=status,
            queue=queue,
            doc_kind="invoice",
            invoice_number="260104417",
            validation=[{"name": "line_math", "ok": False, "fields": ["lines[1].line_net"], "detail": ""}],
            matching={"supplier": "98391267", "order": "OB1", "findings": [{"kind": "price_diff", "line": 0, "detail": ""}], "lines": []},
            routing=[{"rule": "I7", "detail": "price_diff"}],
        )  # fmt: skip
        s.add(inv)
        await s.flush()
        doc = Document(
            case_id=inv.id,
            filename="invoice.pdf",
            mime_type="application/pdf",
            sha256="b" * 64,
            storage_path="x",
            doc_type="invoice",
            page_count=1,
        )
        s.add(doc)
        await s.flush()
        s.add(
            DocCell(
                document_id=doc.id, page=1, tbl=0, item=0, line=0, col=0, header="popis",
                text="Šampón", bbox={"x0": 0.1, "y0": 0.5, "x1": 0.4, "y1": 0.52},
            )
        )  # fmt: skip
        ids = {}
        for name, value in [
            ("supplier_name", "BioFlora s.r.o."),
            ("supplier_iban", "SK89 0200 0000 0076 9943 1836"),
            ("issued_by", "<PERSON_1>"),
            ("lines[1].line_net", "5,41"),
        ]:
            f = ExtractedField(
                case_id=inv.id, document_id=doc.id, field=name, value_raw=value,
                value_norm=value, method="llm_text", grounded=True, confidence=0.9,
            )  # fmt: skip
            s.add(f)
            await s.flush()
            ids[name] = f.id
        await Vault(KEY).store(s, inv.id, {"<PERSON_1>": ("PERSON", "Emanuel Slovák")})
        s.add(
            PipelineStepRun(
                case_id=inv.id, step="validate", status="ok",
                finished_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )  # fmt: skip
        return inv.id, ids


async def test_intake_creates_an_invoice_and_enqueues_it(client):
    r = await client.post(
        "/api/invoices",
        files={"file": ("faktura.pdf", PDF, "application/pdf")},
        headers={"X-Intake-Token": "intake-token"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["reference"].startswith("FA-2026-") and body["status"] == "RECEIVED"
    assert ("advance", (body["id"],)) in client._transport.app.state.arq.jobs  # type: ignore[attr-defined]


async def test_intake_refuses_other_files(client):
    r = await client.post(
        "/api/invoices",
        files={"file": ("faktura.docx", b"PK..", "application/octet-stream")},
        headers={"X-Intake-Token": "intake-token"},
    )
    assert r.status_code == 415


async def test_queue_and_detail_show_checks_and_real_values(client):
    iid, _ = await make_invoice()
    await login(client)
    queue = (await client.get("/api/review/invoices", params={"queue": "standard"})).json()
    row = next(q for q in queue if q["id"] == str(iid))
    assert (row["supplier"], row["findings"], row["rule"]) == ("BioFlora s.r.o.", 2, "I7")
    detail = (await client.get(f"/api/review/invoices/{iid}")).json()
    header = {f["field"]: f["value"] for f in detail["header"]}
    assert header["issued_by"] == "Emanuel Slovák"
    assert detail["lines"][0]["n"] == 1 and detail["lines"][0]["row"]["page"] == 1
    assert detail["lines"][0]["fields"]["line_net"]["value"] == "5,41"
    assert detail["matching"]["findings"][0]["kind"] == "price_diff"


async def test_the_agent_sees_tokens(client):
    iid, _ = await make_invoice()
    detail = (
        await client.get(f"/api/review/invoices/{iid}", headers={"X-Service-Token": "svc-token"})
    ).json()
    assert "Slovák" not in str(detail)


async def test_a_correction_is_normalized_and_blocks_approval_until_reassessed(client):
    iid, ids = await make_invoice()
    await login(client)
    version = (await client.get(f"/api/review/invoices/{iid}")).json()["version"]
    r = await client.patch(
        f"/api/review/fields/{ids['lines[1].line_net']}", json={"value": "5,31", "version": version}
    )
    assert r.status_code == 200, r.text
    assert r.json()["value_norm"] == "5.31"  # comma decimal, not "531"
    # Company data stays out of the vault: the IBAN is not a person's.
    r = await client.patch(
        f"/api/review/fields/{ids['supplier_iban']}",
        json={"value": "SK31 1200 0000 1987 4263 7541"},
    )
    assert r.json()["value"] == "SK31 1200 0000 1987 4263 7541"
    detail = (await client.get(f"/api/review/invoices/{iid}")).json()
    assert detail["needs_revalidation"]
    r = await client.post(f"/api/review/invoices/{iid}/actions/approve", json={})
    assert r.status_code == 409 and "reassess" in r.json()["detail"]
    r = await client.post(f"/api/review/invoices/{iid}/actions/reassess", json={})
    assert r.json()["status"] == "EXTRACTED"


async def test_approve_moves_on_and_is_audited(client):
    iid, _ = await make_invoice()
    await login(client)
    r = await client.post(f"/api/review/invoices/{iid}/actions/approve", json={"note": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    async with db_session.session_scope() as s:
        from sqlalchemy import select

        actions = (await s.scalars(select(AuditLog.action).where(AuditLog.case_id == iid))).all()
    assert "approve" in actions


async def test_fraud_review_needs_a_senior(client):
    iid, _ = await make_invoice(queue="fraud_review")
    await login(client)
    assert (
        await client.post(f"/api/review/invoices/{iid}/actions/approve", json={})
    ).status_code == 403
    await login(client, "senior.demo")
    assert (await client.post(f"/api/review/invoices/{iid}/actions/reject", json={})).json()[
        "status"
    ] == "REJECTED"


async def test_a_claim_endpoint_does_not_serve_an_invoice(client):
    iid, _ = await make_invoice()
    await login(client)
    assert (await client.get(f"/api/review/claims/{iid}")).status_code == 404
