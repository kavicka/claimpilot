# ruff: noqa: F811  (the wholesale_pdf fixture is imported from the steps tests)
"""An invoice with more items than the limit goes back to NEEDS_INFO with the reason."""

import pytest
from sqlalchemy import select
from test_invoice_steps_db import new_invoice, wholesale_pdf  # noqa: F401

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import DocCell, Document, Invoice
from claimpilot_core.settings import get_settings
from claimpilot_worker import pipeline
from claimpilot_worker.validation.settings import config, max_items

pytestmark = pytest.mark.db
TEST_DB = "postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5438/claimpilot_test"


@pytest.fixture(autouse=True)
def test_database(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAIMPILOT_DATABASE_URL", TEST_DB)
    monkeypatch.setenv("CLAIMPILOT_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    import claimpilot_worker.steps  # noqa: F401  registers the steps

    yield
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()


def test_the_limit_is_in_the_config_and_defaults_to_400():
    assert config()["limits"]["max_items"] == 400
    assert max_items() == 400


async def test_too_many_items_go_to_needs_info_without_extraction(
    wholesale_pdf,
    tmp_path,
    monkeypatch,
):
    data, v = wholesale_pdf
    assert len(v["lines"]) > 1
    monkeypatch.setattr("claimpilot_worker.steps.invoice.max_items", lambda: 1)
    iid = await new_invoice(data, tmp_path)
    assert await pipeline.advance({"job_try": 1, "settings": get_settings()}, str(iid)) == (
        "NEEDS_INFO"
    )
    async with db_session.session_scope() as s:
        inv = await s.get(Invoice, iid)
        doc = (await s.scalars(select(Document).where(Document.case_id == iid))).one()
        cells = (await s.scalars(select(DocCell).where(DocCell.document_id == doc.id))).all()
    assert inv is not None and inv.status == "NEEDS_INFO"
    assert "too many items, split the invoice" in (doc.problem or "")
    assert not cells  # nothing is kept that a retry would have to delete
    assert not (tmp_path / "renders" / str(doc.id)).exists()


async def test_an_invoice_at_the_limit_goes_on(wholesale_pdf, tmp_path, monkeypatch):
    data, v = wholesale_pdf
    monkeypatch.setattr("claimpilot_worker.steps.invoice.max_items", lambda: len(v["lines"]))
    iid = await new_invoice(data, tmp_path)
    assert await pipeline.advance({"job_try": 1, "settings": get_settings()}, str(iid)) == "PARSED"
