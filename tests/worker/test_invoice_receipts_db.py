"""A receipt is invoiced once: a second invoice for the same goods is flagged on every line, with
the whole pipeline and the mock ERP (compose Postgres, `make test-db`)."""

import copy
import json
import uuid

import httpx
import pytest
from sqlalchemy import delete, select
from test_invoice_steps_db import GtGateway, new_invoice, test_database  # noqa: F401

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import Case, Invoice
from claimpilot_core.settings import get_settings, repo_root
from claimpilot_worker import pipeline

pytestmark = pytest.mark.db
ROOT = repo_root() / "data" / "synthetic" / "invoices"


def clean_invoice() -> dict:
    """A dev invoice with an order, a receipt and no planted finding (text layouts only)."""
    for path in sorted((ROOT / "dev").glob("*/ground_truth.json")):
        data = json.loads(path.read_text("utf-8"))
        order = data["header"].get("order_number", {})
        if (
            not data["findings"]
            and data["kind"] == "invoice"
            and data["layout"] != "scan_en"
            and order.get("page")
        ):
            return data
    raise AssertionError("no clean dev invoice with an order")


def with_number(gt: dict) -> dict:
    out = copy.deepcopy(gt)
    number = f"T{uuid.uuid4().hex[:9].upper()}"
    out["header"]["invoice_number"] |= {"printed": number, "value": number}
    return out


async def run_to_review(gt: dict, pdf: bytes, tmp_path, client) -> uuid.UUID:
    iid = await new_invoice(pdf, tmp_path)
    ctx = {"job_try": 1, "settings": get_settings(), "gateway": GtGateway(gt), "erp_client": client}
    for expected in ("PARSED", "REDACTED", "EXTRACTED", "VALIDATED", "MATCHED", "ROUTED"):
        assert await pipeline.advance(ctx, str(iid)) == expected
    return iid


async def test_the_second_invoice_for_the_same_receipt_is_flagged(tmp_path, monkeypatch):
    from claimpilot_core_mock import erp
    from claimpilot_datagen.invoices.render import render
    from claimpilot_datagen.invoices.sampler import build_invoice_set

    monkeypatch.setenv("ERP_MOCK_DATA", str(ROOT))
    erp.records.cache_clear()
    gt = clean_invoice()
    inv = next(i for i in build_invoice_set(42).invoices if i.invoice_id == gt["invoice_id"])
    pdf, _ext, _v = render(inv, 42)
    order = gt["header"]["order_number"]["printed"]
    async with db_session.session_scope() as s:  # the test db keeps rows of earlier runs
        old = select(Invoice.id).where(Invoice.matching["order"].as_string() == order)
        await s.execute(delete(Case).where(Case.id.in_(old)))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=erp.app), base_url="http://erp"
    ) as client:
        first = await run_to_review(with_number(gt), pdf, tmp_path, client)
        second = await run_to_review(with_number(gt), pdf, tmp_path, client)

    async with db_session.session_scope() as s:
        one, two = await s.get(Invoice, first), await s.get(Invoice, second)
        assert one is not None and two is not None
        assert [f["kind"] for f in one.matching["findings"]] == []
        assert [r["rule"] for r in one.routing] == []
        present = [ln for ln in gt["lines"] if ln.get("page") is not None]
        flagged = [f for f in two.matching["findings"] if f["kind"] == "already_invoiced"]
        assert sorted(f["line"] for f in flagged) == list(range(len(present)))
        assert [r["rule"] for r in two.routing] == ["I7"]
        assert two.queue == "standard"
    erp.records.cache_clear()
