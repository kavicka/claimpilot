"""Pipeline orchestration: one arq job advances a case by one step and enqueues the next.

Steps are registered per (case kind, status), and every move goes through the kind's state
machine. Each step records a pipeline_steps row (status, latency, tokens, models). A step that
keeps failing is retried up to MAX_TRIES times by arq; after that the case moves to FAILED and
shows up in the dead-letter list in the UI.
"""

import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog
from arq import Retry
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import Case, PipelineStepRun
from claimpilot_core.db.session import session_scope
from claimpilot_core.domain import CaseKind, ClaimStatus, InvoiceStatus, PipelineStep
from claimpilot_core.llm.gateway import collect_calls
from claimpilot_core.observability import get_tracer
from claimpilot_core.state_machine import Actor, for_kind

log = structlog.get_logger(__name__)
MAX_TRIES = 3

# A step takes the case of its kind (Claim, later Invoice) and returns the next status.
StepFn = Callable[[AsyncSession, Any, dict[str, Any]], Awaitable[StrEnum]]

STATUSES: dict[CaseKind, type[StrEnum]] = {
    CaseKind.CLAIM: ClaimStatus,
    CaseKind.INVOICE: InvoiceStatus,
}
# (kind, status) -> (step name, function); filled by claimpilot_worker.steps
STEPS: dict[tuple[CaseKind, str], tuple[PipelineStep, StepFn]] = {}
# Statuses that wait for a person or are final. APPROVED is not one: approval enqueues the
# submission of a claim or the export of an invoice.
WAITING: dict[CaseKind, frozenset[str]] = {
    CaseKind.CLAIM: frozenset({"IN_REVIEW", "NEEDS_INFO", "SUBMITTED", "REJECTED", "FAILED"}),
    CaseKind.INVOICE: frozenset({"IN_REVIEW", "NEEDS_INFO", "EXPORTED", "REJECTED", "FAILED"}),
}


def register(
    status: StrEnum, step: PipelineStep, kind: CaseKind = CaseKind.CLAIM
) -> Callable[[StepFn], StepFn]:
    def deco(fn: StepFn) -> StepFn:
        STEPS[(kind, status.value)] = (step, fn)
        return fn

    return deco


async def advance(ctx: dict[str, Any], case_id: str) -> str:
    """arq job: run the step for the case's current status, then enqueue the next one."""
    cid = uuid.UUID(case_id)
    step: PipelineStep | None = None
    started = time.perf_counter()
    try:
        # The commit at the end of the scope is inside the try too: a failed flush carries the
        # statement parameters (document text) and must go through safe_error like any other.
        async with session_scope() as session:
            case = await session.get(Case, cid)
            if case is None:
                return "missing"
            kind = CaseKind(case.kind)
            status = STATUSES[kind](case.status)
            if status in WAITING[kind] or (kind, status.value) not in STEPS:
                return status.value
            step, fn = STEPS[(kind, status.value)]
            run = PipelineStepRun(
                case_id=cid, step=step.value, status="running", attempt=ctx.get("job_try", 1)
            )
            session.add(run)
            await session.flush()
            structlog.contextvars.bind_contextvars(
                case_id=case_id, kind=kind.value, step=step.value
            )
            with (
                get_tracer().step(case_id, step.value, reference=case.reference) as trace_id,
                collect_calls() as calls,
            ):
                run.trace_id = trace_id
                new_status = await fn(session, case, ctx)
            case.status = for_kind(kind).transition(status, new_status, Actor.SYSTEM).value
            case.error = None
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
        structlog.contextvars.unbind_contextvars("case_id", "kind", "step")
    log.info("step.ok", case_id=case_id, step=step.value, status=new_status.value)
    if new_status not in WAITING[kind] and "redis" in ctx:
        await ctx["redis"].enqueue_job("advance", case_id)
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
                case_id=cid,
                step=step.value,
                status="error",
                attempt=tries,
                finished_at=datetime.now(UTC),
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=detail[:2000],
            )
        )
        case = await session.get(Case, cid)
        if case is not None and tries >= MAX_TRIES:
            kind = CaseKind(case.kind)
            status = STATUSES[kind]
            case.status = (
                for_kind(kind).transition(status(case.status), status("FAILED"), Actor.SYSTEM).value
            )
            case.error = detail[:2000]
    log.error(
        "step.error",
        case_id=str(cid),
        step=step.value,
        attempt=tries,
        error=detail,
    )
    if tries < MAX_TRIES:
        # A model server or database that is down needs minutes, not seconds, to come back.
        raise Retry(defer=tries * (60 if transient(exc) else 5)) from None  # no cause: arq logs it
    return "FAILED"


def transient(exc: BaseException) -> bool:
    """Errors of the infrastructure rather than of the case: connection and timeout errors."""
    import httpx
    from sqlalchemy.exc import OperationalError

    from claimpilot_core.llm.ollama import OllamaError

    if isinstance(exc, OllamaError):
        return str(exc).startswith("ollama 5")  # the server failed, not the request
    return isinstance(exc, httpx.TransportError | OperationalError | ConnectionError | TimeoutError)


ACTIVE: dict[CaseKind, list[str]] = {
    kind: [s.value for s in STATUSES[kind] if s.value not in WAITING[kind]] for kind in CaseKind
}


async def sweep(ctx: dict[str, Any], *, older_than_minutes: int = 20) -> int:
    """Re-enqueue cases that stopped moving: a job lost when Redis restarted, or an enqueue that
    failed after the api had committed. The threshold is above the job timeout (15 min), so a
    step that is still running is not picked up; the job id makes one sweep per case version."""
    from datetime import timedelta

    from sqlalchemy import or_, select

    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Case.id, Case.version).where(
                    or_(
                        *(
                            (Case.kind == kind.value) & Case.status.in_(statuses)
                            for kind, statuses in ACTIVE.items()
                        )
                    ),
                    Case.updated_at < cutoff,
                )
            )
        ).all()
    for cid, version in rows:
        await ctx["redis"].enqueue_job("advance", str(cid), _job_id=f"sweep:{cid}:{version}")
    if rows:
        log.info("sweep.enqueued", cases=len(rows))
    return len(rows)
