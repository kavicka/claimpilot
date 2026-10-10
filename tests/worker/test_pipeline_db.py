"""Pipeline orchestration against the compose Postgres (test database). Run with `make test-db`."""

import uuid

import pytest
from arq import Retry
from sqlalchemy import func, select, text

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


async def test_unreadable_files_go_back_to_the_client(monkeypatch, tmp_path):
    import pymupdf

    from claimpilot_core.db.models import Document, Summary
    from claimpilot_worker.steps.ingest import ingest

    monkeypatch.setenv("CLAIMPILOT_STORAGE_DIR", str(tmp_path))
    get_settings.cache_clear()
    pipeline.STEPS[S.RECEIVED] = (PipelineStep.INGEST, ingest)
    cid = await new_claim()
    locked = pymupdf.open()
    locked.new_page().insert_text((72, 72), "Faktúra")
    files = {
        "faktura.pdf": locked.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="1234"),
        "foto.jpg": b"\xff\xd8\xff" + b"cut off",
    }
    async with db_session.session_scope() as s:
        for name, data in files.items():
            rel = f"claims/{cid}/{name}"
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_bytes(data)
            s.add(
                Document(
                    claim_id=cid, filename=name, mime_type="x", sha256="0" * 64, storage_path=rel
                )
            )
    assert await pipeline.advance({"job_try": 1}, str(cid)) == "NEEDS_INFO"
    async with db_session.session_scope() as s:
        docs = {
            d.filename: d.problem
            for d in await s.scalars(select(Document).where(Document.claim_id == cid))
        }
        request = (await s.scalars(select(Summary).where(Summary.claim_id == cid))).one()
    assert docs == {"faktura.pdf": "protected by a password", "foto.jpg": "damaged or not an image"}
    assert "„faktura.pdf“ je chránený heslom" in request.text
    # Run it again (a retry, or a new upload): still exactly one request to the client.
    async with db_session.session_scope() as s:
        (await s.get(Claim, cid)).status = "RECEIVED"
    await pipeline.advance({"job_try": 1}, str(cid))
    async with db_session.session_scope() as s:
        assert len((await s.scalars(select(Summary).where(Summary.claim_id == cid))).all()) == 1


async def test_infrastructure_errors_wait_longer_before_a_retry():
    import httpx

    @pipeline.register(S.RECEIVED, PipelineStep.INGEST)
    async def ollama_down(session, claim, ctx):
        raise httpx.ConnectError("connection refused")

    cid = await new_claim()
    with pytest.raises(Retry) as info:
        await pipeline.advance({"job_try": 2}, str(cid))
    assert info.value.defer_score == 120_000  # 2nd try: 2 x 60 s

    @pipeline.register(S.RECEIVED, PipelineStep.INGEST)
    async def bad_data(session, claim, ctx):
        raise ValueError("unexpected field")

    with pytest.raises(Retry) as info:
        await pipeline.advance({"job_try": 2}, str(cid))
    assert info.value.defer_score == 10_000


class FakeRedis:
    def __init__(self):
        self.jobs = []

    async def enqueue_job(self, name, *args, _job_id=None):
        self.jobs.append((name, args, _job_id))


async def test_sweep_resumes_claims_that_stopped_moving():
    from sqlalchemy import update

    stuck = await new_claim(S.EXTRACTED)  # its job was lost when Redis restarted
    fresh = await new_claim(S.EXTRACTED)  # a step is still running on it
    waiting = await new_claim(S.IN_REVIEW)  # waits for a person: not the sweep's business
    async with db_session.session_scope() as s:
        await s.execute(
            update(Claim)
            .where(Claim.id.in_([stuck, waiting]))
            .values(updated_at=func.now() - text("interval '2 hours'"))
        )
    redis = FakeRedis()
    await pipeline.sweep({"redis": redis})
    swept = [args[0] for _, args, _ in redis.jobs]
    assert str(stuck) in swept
    assert str(fresh) not in swept and str(waiting) not in swept
    job_id = next(j for _, args, j in redis.jobs if args[0] == str(stuck))
    assert job_id == f"sweep:{stuck}:1"  # one sweep per claim version, however often it runs
