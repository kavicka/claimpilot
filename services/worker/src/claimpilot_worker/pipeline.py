"""Pipeline orchestration: one arq job advances a claim by one step and enqueues the next.

Each step records a pipeline_steps row (status, latency, tokens, models). A step that keeps failing
is retried up to MAX_TRIES times by arq; after that the claim moves to FAILED and shows up in the
dead-letter list in the UI.
"""

import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import Claim, PipelineStepRun
from claimpilot_core.db.session import session_scope
from claimpilot_core.domain import ClaimStatus as S
from claimpilot_core.domain import PipelineStep
from claimpilot_core.llm.gateway import collect_calls
from claimpilot_core.observability import get_tracer
from claimpilot_core.state_machine import Actor, transition

log = structlog.get_logger(__name__)
MAX_TRIES = 3

StepFn = Callable[[AsyncSession, Claim, dict[str, Any]], Awaitable[S]]

# status -> (step name, function); filled by claimpilot_worker.steps
STEPS: dict[S, tuple[PipelineStep, StepFn]] = {}
# Statuses that wait for a person or are final. APPROVED is not one: approval enqueues submission.
WAITING = {S.IN_REVIEW, S.NEEDS_INFO, S.SUBMITTED, S.REJECTED, S.FAILED}


def register(status: S, step: PipelineStep) -> Callable[[StepFn], StepFn]:
    def deco(fn: StepFn) -> StepFn:
        STEPS[status] = (step, fn)
        return fn

    return deco


async def advance(ctx: dict[str, Any], claim_id: str) -> str:
    """arq job: run the step for the claim's current status, then enqueue the next one."""
    cid = uuid.UUID(claim_id)
    step: PipelineStep | None = None
    started = time.perf_counter()
    try:
        # The commit at the end of the scope is inside the try too: a failed flush carries the
        # statement parameters (document text) and must go through safe_error like any other.
        async with session_scope() as session:
            claim = await session.get(Claim, cid)
            if claim is None:
                return "missing"
            status = S(claim.status)
            if status in WAITING or status not in STEPS:
                return status.value
            step, fn = STEPS[status]
            run = PipelineStepRun(
                claim_id=cid, step=step.value, status="running", attempt=ctx.get("job_try", 1)
            )
            session.add(run)
            await session.flush()
            structlog.contextvars.bind_contextvars(claim_id=claim_id, step=step.value)
            with (
                get_tracer().step(claim_id, step.value, reference=claim.reference) as trace_id,
                collect_calls() as calls,
            ):
                run.trace_id = trace_id
                new_status = await fn(session, claim, ctx)
            claim.status = transition(status, new_status, Actor.SYSTEM).value
            claim.error = None
            run.status = "ok"
            run.finished_at = datetime.now(UTC)
            run.latency_ms = int((time.perf_counter() - started) * 1000)
            run.tokens_in = sum(c.tokens_in for c in calls)
            run.tokens_out = sum(c.tokens_out for c in calls)
            run.models = sorted({c.model for c in calls})
    except Exception as exc:
        if step is None:
            raise RuntimeError(safe_error(exc)) from None
        return await _fail(ctx, cid, step, started, exc)
    finally:
        structlog.contextvars.unbind_contextvars("claim_id", "step")
    log.info("step.ok", claim_id=claim_id, step=step.value, status=new_status.value)
    if new_status not in WAITING and "redis" in ctx:
        await ctx["redis"].enqueue_job("advance", claim_id)
    return new_status.value


def safe_error(exc: BaseException) -> str:
    """Type and first line only. Database errors carry the statement parameters (document text,
    names) in their message; those must never reach logs or the dead-letter list."""
    orig = getattr(exc, "orig", None)
    source = orig if orig is not None else exc
    first_line = (str(source).splitlines() or [""])[0][:300]
    return f"{type(source).__name__}: {first_line}"


async def _fail(
    ctx: dict[str, Any], cid: uuid.UUID, step: PipelineStep, started: float, exc: Exception
) -> str:
    tries = ctx.get("job_try", 1)
    detail = safe_error(exc)
    async with session_scope() as session:
        session.add(
            PipelineStepRun(
                claim_id=cid,
                step=step.value,
                status="error",
                attempt=tries,
                finished_at=datetime.now(UTC),
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=detail[:2000],
            )
        )
        claim = await session.get(Claim, cid)
        if claim is not None and tries >= MAX_TRIES:
            claim.status = transition(S(claim.status), S.FAILED, Actor.SYSTEM).value
            claim.error = detail[:2000]
    log.error(
        "step.error",
        claim_id=str(cid),
        step=step.value,
        attempt=tries,
        error=detail,
    )
    if tries < MAX_TRIES:
        # A model server or database that is down needs minutes, not seconds, to come back.
        raise Retry(defer=tries * (60 if transient(exc) else 5)) from None  # no cause: arq logs it
    return S.FAILED.value


def transient(exc: BaseException) -> bool:
    """Errors of the infrastructure rather than of the claim: connection and timeout errors."""
    import httpx
    from sqlalchemy.exc import OperationalError

    from claimpilot_core.llm.ollama import OllamaError

    if isinstance(exc, OllamaError):
        return str(exc).startswith("ollama 5")  # the server failed, not the request
    return isinstance(exc, httpx.TransportError | OperationalError | ConnectionError | TimeoutError)


ACTIVE = [S.RECEIVED, S.PARSED, S.REDACTED, S.EXTRACTED, S.ROUTED, S.ASSESSED, S.APPROVED]


async def sweep(ctx: dict[str, Any], *, older_than_minutes: int = 20) -> int:
    """Re-enqueue claims that stopped moving: a job lost when Redis restarted, or an enqueue that
    failed after the api had committed. The threshold is above the job timeout (15 min), so a
    step that is still running is not picked up; the job id makes one sweep per claim version."""
    from datetime import timedelta

    from sqlalchemy import select

    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Claim.id, Claim.version).where(
                    Claim.status.in_([s.value for s in ACTIVE]), Claim.updated_at < cutoff
                )
            )
        ).all()
    for cid, version in rows:
        await ctx["redis"].enqueue_job("advance", str(cid), _job_id=f"sweep:{cid}:{version}")
    if rows:
        log.info("sweep.enqueued", claims=len(rows))
    return len(rows)
