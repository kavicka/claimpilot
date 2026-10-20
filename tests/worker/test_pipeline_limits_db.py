"""Hard limits of the pipeline: step time budgets, the poison guard, too many items."""

import asyncio
import uuid

import pytest
from arq import Retry
from sqlalchemy import func, select, text, update

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import (
    AuditLog,
    Case,
    Claim,
    Invoice,
    PipelineStepRun,
    User,
)
from claimpilot_core.domain import CaseKind, InvoiceStatus, PipelineStep
from claimpilot_core.domain import ClaimStatus as S
from claimpilot_core.settings import (
    Settings,
    get_settings,
    longest_step_budget,
    step_budget,
)
from claimpilot_worker import pipeline

TEST_DB = "postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5438/claimpilot_test"


class FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[str] = []

    async def enqueue_job(self, name, *args, _job_id=None):
        self.jobs.append(args[0])


def test_budgets_default_per_kind_and_step():
    s = Settings(_env_file=None)
    assert step_budget(s, "claim", "extract") == s.step_timeout_s == 840
    assert step_budget(s, "invoice", "ingest") == 840
    assert step_budget(s, "invoice", "extract") == 3600  # 34 sequential calls need an hour
    assert longest_step_budget(s) == 3600


def test_budgets_can_be_set_from_the_environment(monkeypatch):
    monkeypatch.setenv("CLAIMPILOT_STEP_TIMEOUTS", '{"claim.extract": 1200}')
    monkeypatch.setenv("CLAIMPILOT_STEP_TIMEOUT_S", "300")
    s = Settings(_env_file=None)
    assert step_budget(s, "claim", "extract") == 1200
    assert step_budget(s, "claim", "route") == 300
    assert longest_step_budget(s) == 1200


def test_the_arq_job_limit_sits_above_the_longest_budget():
    from claimpilot_worker.main import WorkerSettings

    assert WorkerSettings.job_timeout > longest_step_budget(get_settings())
    assert WorkerSettings.health_check_interval == 30


@pytest.mark.db
class TestWithDatabase:
    @pytest.fixture(autouse=True)
    def test_database(self, monkeypatch):
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

    async def new_claim(self, status: S = S.RECEIVED) -> uuid.UUID:
        async with db_session.session_scope() as s:
            claim = Claim(reference=f"L-{uuid.uuid4().hex[:10]}", status=status.value)
            s.add(claim)
            await s.flush()
            return claim.id

    async def new_invoice(self, status: InvoiceStatus) -> uuid.UUID:
        async with db_session.session_scope() as s:
            invoice = Invoice(reference=f"L-{uuid.uuid4().hex[:10]}", status=status.value)
            s.add(invoice)
            await s.flush()
            return invoice.id

    async def age(self, *ids: uuid.UUID, minutes: int) -> None:
        async with db_session.session_scope() as s:
            await s.execute(
                update(Case)
                .where(Case.id.in_(ids))
                .values(updated_at=func.now() - text(f"interval '{minutes} minutes'"))
            )

    async def add_errors(self, cid: uuid.UUID, step: str, n: int) -> None:
        async with db_session.session_scope() as s:
            for attempt in range(1, n + 1):
                s.add(
                    PipelineStepRun(
                        case_id=cid,
                        step=step,
                        status="error",
                        attempt=attempt,
                        error="RuntimeError: boom",
                    )
                )

    # --- time budget --------------------------------------------------------------------

    async def test_a_step_over_its_budget_fails_the_case_at_once(self):
        @pipeline.register(S.RECEIVED, PipelineStep.INGEST)
        async def hangs(session, claim, ctx):
            await asyncio.sleep(30)
            return S.PARSED

        cid = await self.new_claim()
        settings = Settings(_env_file=None, database_url=TEST_DB, step_timeout_s=0.05)  # type: ignore[arg-type]
        # first try, so a normal error would be retried: a timeout is not
        assert await pipeline.advance({"job_try": 1, "settings": settings}, str(cid)) == "FAILED"
        async with db_session.session_scope() as s:
            claim = await s.get(Claim, cid)
            runs = (
                await s.scalars(select(PipelineStepRun).where(PipelineStepRun.case_id == cid))
            ).all()
        assert claim is not None and claim.status == "FAILED"
        assert "time budget" in (claim.error or "") and "ingest" in (claim.error or "")
        assert [(r.step, r.status) for r in runs] == [("ingest", "error")]

    async def test_a_fast_step_is_not_affected_by_the_budget(self):
        @pipeline.register(S.RECEIVED, PipelineStep.INGEST)
        async def quick(session, claim, ctx):
            await asyncio.sleep(0.01)
            return S.PARSED

        cid = await self.new_claim()
        settings = Settings(_env_file=None, database_url=TEST_DB, step_timeout_s=5)  # type: ignore[arg-type]
        assert await pipeline.advance({"job_try": 1, "settings": settings}, str(cid)) == "PARSED"

    async def test_an_invoice_extraction_gets_its_longer_budget(self):
        seen = []

        @pipeline.register(InvoiceStatus.REDACTED, PipelineStep.EXTRACT, kind=CaseKind.INVOICE)
        async def extract(session, case, ctx):
            seen.append(True)
            await asyncio.sleep(0.2)  # over the default 0.05 s, inside the extraction's 5 s
            return InvoiceStatus.EXTRACTED

        iid = await self.new_invoice(InvoiceStatus.REDACTED)
        settings = Settings(  # type: ignore[arg-type]
            _env_file=None,
            database_url=TEST_DB,
            step_timeout_s=0.05,
            step_timeouts={"invoice.extract": 5},
        )
        assert await pipeline.advance({"job_try": 1, "settings": settings}, str(iid)) == "EXTRACTED"
        assert seen

    async def test_other_errors_still_retry(self):
        @pipeline.register(S.RECEIVED, PipelineStep.INGEST)
        async def boom(session, claim, ctx):
            raise RuntimeError("docling crashed")

        cid = await self.new_claim()
        with pytest.raises(Retry):
            await pipeline.advance({"job_try": 1}, str(cid))

    # --- poison guard -------------------------------------------------------------------

    async def test_three_failed_runs_of_one_step_end_it_even_when_arq_starts_counting_again(self):
        @pipeline.register(S.RECEIVED, PipelineStep.INGEST)
        async def boom(session, claim, ctx):
            raise RuntimeError("docling crashed")

        cid = await self.new_claim()
        # two earlier jobs ran twice each, then the sweep enqueued a fresh job: job_try is 1
        for _ in range(2):
            with pytest.raises(Retry):
                await pipeline.advance({"job_try": 1}, str(cid))
        assert await pipeline.advance({"job_try": 1}, str(cid)) == "FAILED"
        async with db_session.session_scope() as s:
            claim = await s.get(Claim, cid)
        assert claim is not None and claim.status == "FAILED"

    async def test_the_sweep_fails_a_poison_case_instead_of_enqueueing_it(self):
        poison = await self.new_claim(S.EXTRACTED)
        sick = await self.new_claim(S.EXTRACTED)
        pipeline.STEPS[(CaseKind.CLAIM, "EXTRACTED")] = (PipelineStep.EXTRACT, None)  # type: ignore[assignment]
        await self.add_errors(poison, "extract", 3)
        await self.add_errors(sick, "extract", 2)
        await self.age(poison, sick, minutes=120)

        redis = FakeRedis()
        await pipeline.sweep({"redis": redis})
        assert str(sick) in redis.jobs and str(poison) not in redis.jobs
        async with db_session.session_scope() as s:
            claim = await s.get(Claim, poison)
        assert claim is not None and claim.status == "FAILED"
        assert "extract" in (claim.error or "") and "3" in (claim.error or "")

    async def test_errors_before_a_handlers_retry_do_not_count(self):
        cid = await self.new_claim(S.EXTRACTED)
        pipeline.STEPS[(CaseKind.CLAIM, "EXTRACTED")] = (PipelineStep.EXTRACT, None)  # type: ignore[assignment]
        await self.add_errors(cid, "extract", 3)
        async with db_session.session_scope() as s:
            user = User(
                username=f"u-{uuid.uuid4().hex[:8]}",
                display_name="T",
                role="handler",
                password_hash="x",
            )
            s.add(user)
            await s.flush()
            s.add(AuditLog(case_id=cid, user_id=user.id, action="retry", details={}))
        await self.age(cid, minutes=120)

        redis = FakeRedis()
        await pipeline.sweep({"redis": redis})
        assert str(cid) in redis.jobs

    async def test_the_sweep_waits_for_a_running_long_budget(self):
        pipeline.STEPS[(CaseKind.INVOICE, "REDACTED")] = (PipelineStep.EXTRACT, None)  # type: ignore[assignment]
        running = await self.new_invoice(InvoiceStatus.REDACTED)  # 30 min into an extraction
        lost = await self.new_invoice(InvoiceStatus.REDACTED)  # past the extraction budget
        await self.age(running, minutes=30)
        await self.age(lost, minutes=3600 // 60 + 30)

        redis = FakeRedis()
        await pipeline.sweep({"redis": redis})
        assert str(lost) in redis.jobs and str(running) not in redis.jobs
