"""The export step against the compose Postgres and the mock ERP: a crash between the POST and the
commit exports once, a taken number is a refusal, and every outcome is audited. Run with
`make test-db`."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from arq import Retry
from sqlalchemy import delete, select, update
from test_invoice_steps_db import GtGateway, new_invoice

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import AuditLog, Case, Invoice
from claimpilot_core.settings import get_settings, repo_root
from claimpilot_core_mock import erp
from claimpilot_worker import pipeline

pytestmark = pytest.mark.db
TEST_DB = "postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5438/claimpilot_test"


@pytest.fixture(autouse=True)
def test_database(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAIMPILOT_DATABASE_URL", TEST_DB)
    monkeypatch.setenv("CLAIMPILOT_STORAGE_DIR", str(tmp_path))
    monkeypatch.setenv("ERP_MOCK_DATA", str(repo_root() / "data" / "synthetic" / "invoices"))
    monkeypatch.delenv("ERP_MOCK_TOKEN", raising=False)
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    erp.records.cache_clear()
    erp.POSTED.clear()
    erp.KEYS.clear()
    import claimpilot_worker.steps  # noqa: F401  registers the steps

    yield
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    erp.records.cache_clear()
    erp.POSTED.clear()
    erp.KEYS.clear()


class Recorder:
    """An ERP client on the mock app that remembers each POST: key and status."""

    def __init__(self) -> None:
        self.posts: list[tuple[str | None, int]] = []
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=erp.app),
            base_url="http://erp",
            event_hooks={"response": [self._seen]},
        )

    async def _seen(self, resp: httpx.Response) -> None:
        if resp.request.method == "POST":
            self.posts.append((resp.request.headers.get("idempotency-key"), resp.status_code))


class PostAnswers(httpx.AsyncBaseTransport):
    """The mock ERP for lookups; every POST gets this answer instead."""

    def __init__(self, status: int, body: dict | None = None) -> None:
        self.answer = (status, body)
        self.inner = httpx.ASGITransport(app=erp.app)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(self.answer[0], json=self.answer[1])
        return await self.inner.handle_async_request(request)


class Redis:
    def __init__(self) -> None:
        self.jobs: list[str] = []

    async def enqueue_job(self, name: str, case_id: str, **kw: Any) -> None:
        self.jobs.append(case_id)


async def approved_invoice(tmp_path, monkeypatch) -> tuple[uuid.UUID, dict]:
    """A perfectly extracted synthetic invoice, taken through the pipeline to review and approved
    the way the api does."""
    root = repo_root() / "data" / "synthetic" / "invoices"
    gt = None
    for path in sorted((root / "dev").glob("*/ground_truth.json")):
        data = json.loads(path.read_text("utf-8"))
        kinds = {f["kind"] for f in data["findings"]}
        if kinds == {"price_diff"} and data["layout"] != "scan_en" and data["kind"] == "invoice":
            gt = data
            break
    assert gt is not None
    from claimpilot_datagen.invoices.render import render
    from claimpilot_datagen.invoices.sampler import build_invoice_set

    inv = next(i for i in build_invoice_set(42).invoices if i.invoice_id == gt["invoice_id"])
    data, _ext, _v = render(inv, 42)
    async with db_session.session_scope() as s:
        number = gt["header"]["invoice_number"]["value"]
        await s.execute(
            delete(Case).where(
                Case.id.in_(select(Invoice.id).where(Invoice.invoice_number == number))
            )
        )
    iid = await new_invoice(data, tmp_path)
    ctx = {"job_try": 1, "settings": get_settings(), "gateway": GtGateway(gt)}
    for expected in ("PARSED", "REDACTED", "EXTRACTED", "VALIDATED", "MATCHED", "ROUTED"):
        assert await pipeline.advance(ctx, str(iid)) == expected
    assert await pipeline.advance(ctx, str(iid)) == "IN_REVIEW"
    async with db_session.session_scope() as s:
        (await s.get(Invoice, iid)).status = "APPROVED"  # type: ignore[union-attr]
    return iid, gt


async def audit(iid: uuid.UUID) -> list[AuditLog]:
    async with db_session.session_scope() as s:
        rows = await s.scalars(
            select(AuditLog).where(AuditLog.case_id == iid).order_by(AuditLog.id)
        )
        return list(rows)


async def test_a_crash_after_the_post_exports_once(tmp_path, monkeypatch):
    iid, _gt = await approved_invoice(tmp_path, monkeypatch)
    erp_side = Recorder()
    ctx = {"job_try": 1, "settings": get_settings(), "erp_client": erp_side.client}

    # The process dies after the ERP accepted the document and before our commit.
    real = pipeline.for_kind
    calls = {"n": 0}

    def crashing(kind):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("killed before the commit")
        return real(kind)

    monkeypatch.setattr(pipeline, "for_kind", crashing)
    with pytest.raises(Retry):
        await pipeline.advance(ctx, str(iid))
    assert len(erp.POSTED) == 1
    async with db_session.session_scope() as s:
        invoice = await s.get(Invoice, iid)
        assert invoice and invoice.status == "APPROVED" and invoice.erp_id is None
    assert not [r for r in await audit(iid) if r.action == "exported"]

    # APPROVED is an active status, so the sweep re-drives it once it has been still for 20 min.
    assert "APPROVED" in pipeline.ACTIVE[pipeline.CaseKind.INVOICE]
    async with db_session.session_scope() as s:
        await s.execute(
            update(Case)
            .where(Case.id == iid)
            .values(updated_at=datetime.now(UTC) - timedelta(hours=1))
        )
    redis = Redis()
    await pipeline.sweep({"redis": redis})
    assert str(iid) in redis.jobs

    assert await pipeline.advance(ctx, str(iid)) == "EXPORTED"
    assert len(erp.POSTED) == 1, "the ERP stored the invoice once"
    assert erp_side.posts == [(str(iid), 201), (str(iid), 200)]
    async with db_session.session_scope() as s:
        invoice = await s.get(Invoice, iid)
        assert invoice and invoice.erp_id == next(iter(erp.POSTED))
        assert invoice.export and invoice.export["erp_id"] == invoice.erp_id
    exported = [r for r in await audit(iid) if r.action == "exported"]
    assert len(exported) == 1
    d = exported[0].details
    assert d["actor"] == "system" and d["erp_id"] == invoice.erp_id and d["replayed"] is True
    assert len(d["sha256"]) == 64 and d["total"] is not None
    assert exported[0].user_id is None


async def test_a_taken_number_is_a_refusal_not_an_export(tmp_path, monkeypatch):
    iid, _gt = await approved_invoice(tmp_path, monkeypatch)

    # The ERP is down for the first try, which leaves the document on disk.
    dead = httpx.AsyncClient(transport=PostAnswers(503), base_url="http://erp")
    ctx = {"job_try": 1, "settings": get_settings(), "erp_client": dead}
    with pytest.raises(Retry):
        await pipeline.advance(ctx, str(iid))
    # Another invoice row (another key) posted the same document in the meantime.
    body = (tmp_path / "invoices" / str(iid) / "export.xml").read_bytes()
    other = Recorder()
    first = await other.client.post(
        "/invoices", content=body, headers={"Idempotency-Key": "someone-else"}
    )
    assert first.status_code == 201
    existing = first.json()["erp_id"]

    ctx["erp_client"] = other.client
    assert await pipeline.advance(ctx, str(iid)) == "IN_REVIEW"
    async with db_session.session_scope() as s:
        invoice = await s.get(Invoice, iid)
        assert invoice and invoice.status == "IN_REVIEW"
        assert invoice.erp_id is None, "the other document's id is not ours"
        assert invoice.export and invoice.export["existing_erp_id"] == existing
        assert invoice.export["errors"][0]["rule"] == "ERP-DUPLICATE"
    refused = [r for r in await audit(iid) if r.action == "export_refused"]
    assert len(refused) == 1 and refused[0].details["actor"] == "system"
    assert refused[0].details["errors"][0]["rule"] == "ERP-DUPLICATE"
    assert not [r for r in await audit(iid) if r.action == "exported"]
    assert len(erp.POSTED) == 1


async def test_rule_errors_go_back_to_review_and_are_audited(tmp_path, monkeypatch):
    iid, _gt = await approved_invoice(tmp_path, monkeypatch)
    errors = [{"rule": "BR-CO-15", "field": "TaxInclusiveAmount", "message": "totals differ"}]

    transport = PostAnswers(422, {"detail": {"errors": errors}})
    client = httpx.AsyncClient(transport=transport, base_url="http://erp")
    ctx = {"job_try": 1, "settings": get_settings(), "erp_client": client}
    assert await pipeline.advance(ctx, str(iid)) == "IN_REVIEW"
    async with db_session.session_scope() as s:
        invoice = await s.get(Invoice, iid)
        assert invoice and invoice.erp_id is None and invoice.export
        assert invoice.export["errors"] == errors
    refused = [r for r in await audit(iid) if r.action == "export_refused"]
    assert len(refused) == 1 and refused[0].details["errors"] == errors
