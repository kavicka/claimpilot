"""Invoice review API against the test database: intake, queue, detail, corrections, actions."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apitools import KEY, correct, decide, login, make_user
from sqlalchemy import select

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import (
    AuditLog,
    Correction,
    DocCell,
    Document,
    ExtractedField,
    Invoice,
    PipelineStepRun,
)
from claimpilot_core.pii.vault import Vault

pytestmark = pytest.mark.db
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


async def make_invoice(
    queue="standard", status="IN_REVIEW", total=None, currency=None
) -> tuple[uuid.UUID, dict[str, int]]:
    async with db_session.session_scope() as s:
        inv = Invoice(
            reference=f"T-{uuid.uuid4().hex[:8]}",
            status=status,
            queue=queue,
            total=total,
            currency=currency,
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
    r = await correct(client, f"/api/review/invoices/{iid}", ids["lines[1].line_net"], "5,31")
    assert r.status_code == 200, r.text
    assert r.json()["value_norm"] == "5.31"  # comma decimal, not "531"
    # Company data stays out of the vault: the IBAN is not a person's.
    r = await correct(
        client, f"/api/review/invoices/{iid}", ids["supplier_iban"], "SK31 1200 0000 1987 4263 7541"
    )
    assert r.json()["value"] == "SK31 1200 0000 1987 4263 7541"
    detail = (await client.get(f"/api/review/invoices/{iid}")).json()
    assert detail["needs_revalidation"]
    r = await decide(client, f"/api/review/invoices/{iid}", "approve")
    assert r.status_code == 409 and "reassess" in r.json()["detail"]
    r = await decide(client, f"/api/review/invoices/{iid}", "reassess")
    assert r.json()["status"] == "EXTRACTED"


async def test_approve_moves_on_and_is_audited(client):
    iid, _ = await make_invoice()
    await login(client)
    r = await decide(client, f"/api/review/invoices/{iid}", "approve", note="ok")
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    async with db_session.session_scope() as s:
        from sqlalchemy import select

        actions = (await s.scalars(select(AuditLog.action).where(AuditLog.case_id == iid))).all()
    assert "approve" in actions


async def test_fraud_review_needs_a_senior(client):
    iid, _ = await make_invoice(queue="fraud_review")
    await login(client)
    assert (await decide(client, f"/api/review/invoices/{iid}", "approve")).status_code == 403
    await login(client, "senior.demo")
    assert (await decide(client, f"/api/review/invoices/{iid}", "reject")).json()[
        "status"
    ] == "REJECTED"


async def test_a_claim_endpoint_does_not_serve_an_invoice(client):
    iid, _ = await make_invoice()
    await login(client)
    assert (await client.get(f"/api/review/claims/{iid}")).status_code == 404


# --- fraud queue, versions, four eyes, audit ---------------------------------------------------


async def revalidated(iid) -> None:
    """What the worker leaves behind after a reassess: a validation newer than any correction."""
    async with db_session.session_scope() as s:
        s.add(
            PipelineStepRun(
                case_id=iid, step="validate", status="ok", finished_at=datetime.now(UTC)
            )
        )


@pytest.mark.parametrize("queue", ["fraud_review", "senior"])
async def test_a_handler_cannot_walk_a_flagged_invoice_out_of_the_senior_queue(client, queue):
    """Regression: correct the IBAN or number that raised I1/I2, reassess so the invoice is
    routed to `standard`, approve it there. Every step is refused for a plain handler."""
    iid, ids = await make_invoice(queue=queue)
    url = f"/api/review/invoices/{iid}"
    await login(client)  # handler.demo
    assert (
        await correct(client, url, ids["supplier_iban"], "SK31 1200 0000 1987 4263 7541")
    ).status_code == 403
    for action in ("reassess", "retry", "escalate", "approve", "reject", "request-info"):
        r = await decide(client, url, action)
        assert r.status_code == 403, action
        assert "senior" in r.json()["detail"]
    async with db_session.session_scope() as s:
        inv = await s.get(Invoice, iid)
        assert (inv.status, inv.queue) == ("IN_REVIEW", queue)
        assert not (
            await s.scalars(select(Correction).where(Correction.field_id == ids["supplier_iban"]))
        ).all()
        actions = (await s.scalars(select(AuditLog.action).where(AuditLog.case_id == iid))).all()
        assert not actions  # nothing was done, nothing is logged as done


async def test_a_senior_can_correct_and_reassess_in_the_flagged_queue(client):
    iid, ids = await make_invoice(queue="fraud_review")
    url = f"/api/review/invoices/{iid}"
    await login(client, "senior.demo")
    assert (
        await correct(client, url, ids["supplier_iban"], "SK31 1200 0000 1987 4263 7541")
    ).status_code == 200
    assert (await decide(client, url, "reassess")).json()["status"] == "EXTRACTED"


@pytest.mark.parametrize(
    "action", ["approve", "reject", "request-info", "escalate", "reassess", "retry"]
)
async def test_a_decision_needs_the_version_the_handler_saw(client, action):
    iid, _ = await make_invoice()
    await login(client)
    r = await client.post(f"/api/review/invoices/{iid}/actions/{action}", json={})
    assert r.status_code == 428
    assert "version" in r.json()["detail"]
    async with db_session.session_scope() as s:
        assert (await s.get(Invoice, iid)).status == "IN_REVIEW"


async def test_a_correction_needs_the_version_too(client):
    _, ids = await make_invoice()
    await login(client)
    r = await client.patch(f"/api/review/fields/{ids['supplier_iban']}", json={"value": "x"})
    assert r.status_code == 428


async def test_a_stale_version_is_still_a_conflict(client):
    iid, _ = await make_invoice()
    await login(client)
    v = (await client.get(f"/api/review/invoices/{iid}")).json()["version"]
    r = await client.post(f"/api/review/invoices/{iid}/actions/approve", json={"version": v - 1})
    assert r.status_code == 409


@pytest.mark.parametrize(
    ("total", "currency", "blocked"),
    [
        ("5000.00", "EUR", True),
        ("4999.99", "EUR", False),
        ("125000.00", "CZK", True),
        ("124999.99", "CZK", False),
        (None, None, True),  # an amount we cannot read counts as above the limit
    ],
)
async def test_the_corrector_cannot_approve_a_large_invoice(client, total, currency, blocked):
    iid, ids = await make_invoice(total=total, currency=currency)
    url = f"/api/review/invoices/{iid}"
    await login(client)  # handler.demo corrects and reassesses
    assert (await correct(client, url, ids["supplier_name"], "BioFlora a.s.")).status_code == 200
    await revalidated(iid)
    r = await decide(client, url, "approve")
    if blocked:
        assert r.status_code == 403
        assert "another handler" in r.json()["detail"]
        other = await make_user("handler")
        await login(client, other)
        assert (await decide(client, url, "approve")).json()["status"] == "APPROVED"
    else:
        assert r.status_code == 200 and r.json()["status"] == "APPROVED"


async def test_an_invoice_nobody_corrected_is_approved_by_one_person(client):
    iid, _ = await make_invoice(total="90000.00", currency="EUR")
    await login(client)
    assert (await decide(client, f"/api/review/invoices/{iid}", "approve")).status_code == 200


async def test_a_decision_is_audited_with_what_was_decided(client):
    iid, ids = await make_invoice(total="1234.50", currency="EUR")
    url = f"/api/review/invoices/{iid}"
    await login(client)
    await correct(client, url, ids["supplier_name"], "BioFlora a.s.")
    await revalidated(iid)
    version = (await client.get(url)).json()["version"]
    r = await client.post(f"{url}/actions/approve", json={"version": version, "note": "checked"})
    assert r.status_code == 200
    async with db_session.session_scope() as s:
        rows = (
            await s.scalars(select(AuditLog).where(AuditLog.case_id == iid).order_by(AuditLog.id))
        ).all()
    approve = next(a for a in rows if a.action == "approve")
    assert approve.details == {
        "note": "checked",
        "total": "1234.50",
        "currency": "EUR",
        "version": version,
        "queue": "standard",
        "status": "APPROVED",
        "corrected_fields": 1,
    }
    assert approve.user_id is not None
