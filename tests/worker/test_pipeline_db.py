"""Pipeline orchestration against the compose Postgres (test database). Run with `make test-db`."""

import uuid

import pytest
from arq import Retry
from sqlalchemy import select

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import Claim, PipelineStepRun
from claimpilot_core.domain import ClaimStatus as S
from claimpilot_core.domain import PipelineStep
from claimpilot_core.settings import get_settings
from claimpilot_worker import pipeline

pytestmark = pytest.mark.db
TEST_DB = "postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5438/claimpilot_test"


@pytest.fixture(autouse=True)
def test_database(monkeypatch):
    monkeypatch.setenv("CLAIMPILOT_DATABASE_URL", TEST_DB)
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    saved = dict(pipeline.STEPS)
    pipeline.STEPS.clear()
    yield
    pipeline.STEPS.clear()
    pipeline.STEPS.update(saved)
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()


async def new_claim(status: S = S.RECEIVED) -> uuid.UUID:
    async with db_session.session_scope() as s:
        claim = Claim(reference=f"T-{uuid.uuid4().hex[:10]}", status=status.value)
        s.add(claim)
        await s.flush()
        return claim.id


async def load(cid: uuid.UUID) -> tuple[Claim, list[PipelineStepRun]]:
    async with db_session.session_scope() as s:
        claim = await s.get(Claim, cid)
        runs = (
            await s.scalars(select(PipelineStepRun).where(PipelineStepRun.claim_id == cid))
        ).all()
        return claim, list(runs)


async def test_successful_step_moves_the_claim_and_records_the_run():
    @pipeline.register(S.RECEIVED, PipelineStep.INGEST)
    async def ok(session, claim, ctx):
        return S.PARSED

    cid = await new_claim()
    assert await pipeline.advance({"job_try": 1}, str(cid)) == "PARSED"
    claim, runs = await load(cid)
    assert claim.status == "PARSED"
    assert [(r.step, r.status) for r in runs] == [("ingest", "ok")]
    assert runs[0].latency_ms is not None


async def test_failing_step_retries_then_fails_the_claim():
    @pipeline.register(S.RECEIVED, PipelineStep.INGEST)
    async def boom(session, claim, ctx):
        raise RuntimeError("docling crashed")

    cid = await new_claim()
    for attempt in (1, 2):
        with pytest.raises(Retry):
            await pipeline.advance({"job_try": attempt}, str(cid))
        claim, _ = await load(cid)
        assert claim.status == "RECEIVED"
    assert await pipeline.advance({"job_try": 3}, str(cid)) == "FAILED"
    claim, runs = await load(cid)
    assert claim.status == "FAILED"
    assert "docling crashed" in (claim.error or "")
    assert [r.status for r in runs] == ["error", "error", "error"]


async def test_step_returning_an_illegal_status_is_rejected():
    @pipeline.register(S.RECEIVED, PipelineStep.INGEST)
    async def skip_ahead(session, claim, ctx):
        return S.APPROVED  # the system may never approve

    cid = await new_claim()
    with pytest.raises(Retry):
        await pipeline.advance({"job_try": 1}, str(cid))
    claim, _ = await load(cid)
    assert claim.status == "RECEIVED"


async def test_waiting_states_do_nothing():
    cid = await new_claim(S.IN_REVIEW)
    assert await pipeline.advance({"job_try": 1}, str(cid)) == "IN_REVIEW"


def test_safe_error_drops_statement_parameters():
    from sqlalchemy.exc import DataError

    orig = ValueError(
        "value too long for type character varying(16)\n[parameters: {'text': 'Jana Kováčová'}]"
    )
    exc = DataError(
        "INSERT INTO doc_blocks ... {'text__0': 'Jana Kováčová'}", {"text": "Jana Kováčová"}, orig
    )
    msg = pipeline.safe_error(exc)
    assert "Kováčová" not in msg
    assert msg.startswith("ValueError: value too long")


async def test_a_failed_commit_is_recorded_without_the_statement():
    from claimpilot_core.db.models import Summary

    @pipeline.register(S.RECEIVED, PipelineStep.INGEST)
    async def too_long(session, claim, ctx):
        # kind is VARCHAR(32): the error appears only when the scope commits after the step
        session.add(Summary(claim_id=claim.id, kind="x" * 40, language="sk", text="Jana Kováčová"))
        return S.PARSED

    cid = await new_claim()
    with pytest.raises(Retry) as info:
        await pipeline.advance({"job_try": 1}, str(cid))
    assert info.value.__cause__ is None
    claim, runs = await load(cid)
    assert claim.status == "RECEIVED"
    assert [r.status for r in runs] == ["error"]
    assert "Kováčová" not in (runs[0].error or "")
