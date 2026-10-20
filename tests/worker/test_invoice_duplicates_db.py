"""Duplicate detection against the compose Postgres: numbers compared normalized, and two workers
validating the same invoice at once do not both call it the original."""

import asyncio
import random
import uuid

import pytest

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import Invoice
from claimpilot_core.domain import InvoiceStatus as S
from claimpilot_core.identifiers import normalize_invoice_number
from claimpilot_core.settings import get_settings
from claimpilot_worker.steps.invoice import _duplicate_of

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


def fresh_ico() -> str:
    return f"9{random.randrange(10**6, 10**7)}"  # the test db keeps rows: a supplier per test


async def stored(ico, number, status=S.IN_REVIEW.value) -> Invoice:
    async with db_session.session_scope() as s:
        inv = Invoice(
            reference=f"D-{uuid.uuid4().hex[:10]}",
            status=status,
            supplier_ico=ico,
            invoice_number=number,
            invoice_number_norm=normalize_invoice_number(number),
        )
        s.add(inv)
    return inv


async def waiting(ico, number) -> Invoice:
    async with db_session.session_scope() as s:
        inv = Invoice(reference=f"D-{uuid.uuid4().hex[:10]}", status=S.EXTRACTED.value)
        s.add(inv)
    return inv


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("FA-001", "fa 001"),
        ("FA-001", "FA001"),
        ("fa/001", " FA-001 "),
        ("260104417", "260 104 417"),
    ],
)
async def test_the_same_number_written_differently_is_a_duplicate(first, second):
    ico = fresh_ico()
    original = await stored(ico, first)
    candidate = await waiting(ico, second)
    async with db_session.session_scope() as s:
        assert await _duplicate_of(s, candidate, ico, second) == original.reference


async def test_another_supplier_or_another_number_is_no_duplicate():
    ico = fresh_ico()
    await stored(ico, "FA-001")
    candidate = await waiting(ico, "FA-002")
    async with db_session.session_scope() as s:
        assert await _duplicate_of(s, candidate, ico, "FA-002") is None
        assert await _duplicate_of(s, candidate, fresh_ico(), "FA-001") is None
        assert await _duplicate_of(s, candidate, None, "FA-001") is None
        assert await _duplicate_of(s, candidate, ico, " - ") is None


async def test_a_failed_invoice_is_not_the_original():
    ico = fresh_ico()
    await stored(ico, "FA-001", status=S.FAILED.value)
    candidate = await waiting(ico, "FA-001")
    async with db_session.session_scope() as s:
        assert await _duplicate_of(s, candidate, ico, "FA-001") is None


async def test_of_two_concurrent_validations_exactly_one_sees_a_duplicate():
    """Both workers read "no earlier invoice" unless the check is serialized: the lock makes the
    second wait for the first one's commit, then see its number."""
    ico = fresh_ico()
    a, b = await waiting(ico, "FA-77"), await waiting(ico, "fa 77")

    async def validate(invoice: Invoice, number: str) -> str | None:
        async with db_session.session_scope() as s:  # the pipeline's transaction around a step
            mine = await s.get(Invoice, invoice.id)
            duplicate = await _duplicate_of(s, mine, ico, number)
            mine.supplier_ico, mine.invoice_number = ico, number
            mine.invoice_number_norm = normalize_invoice_number(number)
            await asyncio.sleep(0.3)  # the rest of the step; the other worker arrives meanwhile
            return duplicate

    results = await asyncio.gather(validate(a, "FA-77"), validate(b, "fa 77"))
    assert sorted(r is None for r in results) == [False, True], results
    seen = next(r for r in results if r is not None)
    assert seen in {a.reference, b.reference}


async def test_many_concurrent_validations_leave_one_original():
    ico = fresh_ico()
    invoices = [await waiting(ico, "X") for _ in range(5)]

    async def validate(invoice: Invoice, number: str) -> str | None:
        async with db_session.session_scope() as s:
            mine = await s.get(Invoice, invoice.id)
            duplicate = await _duplicate_of(s, mine, ico, number)
            mine.supplier_ico, mine.invoice_number = ico, number
            mine.invoice_number_norm = normalize_invoice_number(number)
            await asyncio.sleep(0.05)
            return duplicate

    numbers = ["INV-9", "inv 9", "Inv/9", "INV9", "inv.9"]
    results = await asyncio.gather(
        *(validate(i, n) for i, n in zip(invoices, numbers, strict=True))
    )
    assert sum(r is None for r in results) == 1
