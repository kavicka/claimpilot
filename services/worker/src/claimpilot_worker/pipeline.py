"""Pipeline orchestration: one arq job advances a case by one step and enqueues the next.

Steps are registered per (case kind, status), and every move goes through the kind's state
machine. Each step records a pipeline_steps row (status, latency, tokens, models). A step that
keeps failing is retried up to MAX_TRIES times by arq; after that the case moves to FAILED and
shows up in the dead-letter list in the UI.
"""

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog
from arq import Retry
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import AuditLog, Case, PipelineStepRun
from claimpilot_core.db.session import session_scope
from claimpilot_core.domain import CaseKind, ClaimStatus, InvoiceStatus, PipelineStep
from claimpilot_core.llm.gateway import collect_calls
from claimpilot_core.observability import get_tracer
from claimpilot_core.settings import get_settings, step_budget
from claimpilot_core.state_machine import Actor, for_kind

log = structlog.get_logger(__name__)
MAX_TRIES = 3


class StepTimeoutError(Exception):
    """A step ran past its time budget (settings.step_timeouts). Retrying a step that took an hour
    only costs another hour, so the case goes to FAILED and a person decides."""


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
                budget = step_budget(ctx.get("settings") or get_settings(), kind.value, step.value)
                try:
                    async with asyncio.timeout(budget) as scope:
                        new_status = await fn(session, case, ctx)
                except TimeoutError:
                    if not scope.expired():
                        raise  # a timeout of the step's own (a socket), not the budget
                    msg = f"{kind.value} {step.value} exceeded its time budget of {budget:g} s"
                    raise StepTimeoutError(msg) from None
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
        await session.flush()
        # arq counts tries per job; a sweep or a restart starts a new job, so count the runs.
        final = (
            tries >= MAX_TRIES
            or isinstance(exc, StepTimeoutError)
            or await failed_runs(session, cid, step.value) >= MAX_TRIES
        )
        if case is not None and final:
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
    if not final:
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


async def failed_runs(session: AsyncSession, case_id: uuid.UUID, step: str) -> int:
    """Error runs of one step since a person last acted on the case (a retry or a reassess
    starts the count again)."""
    last_action = (
        select(func.max(AuditLog.created_at))
        .where(AuditLog.case_id == case_id, AuditLog.user_id.is_not(None))
        .scalar_subquery()
    )
    count = await session.scalar(
        select(func.count())
        .select_from(PipelineStepRun)
        .where(
            PipelineStepRun.case_id == case_id,
            PipelineStepRun.step == step,
            PipelineStepRun.status == "error",
            or_(last_action.is_(None), PipelineStepRun.started_at > last_action),
        )
    )
    return count or 0


async def sweep(ctx: dict[str, Any], *, older_than_minutes: int = 20) -> int:
    """Re-enqueue cases that stopped moving: a job lost when Redis restarted, or an enqueue that
    failed after the api had committed. A case is left alone while its step may still be running
    (the step's time budget plus five minutes, never less than `older_than_minutes`); the job id
    makes one sweep per case version. A case whose step already failed MAX_TRIES times goes to
    FAILED instead: with one worker slot, a poison case would block the queue every cycle."""
    from datetime import timedelta

    settings = ctx.get("settings") or get_settings()
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=older_than_minutes)
    resumable: list[tuple[uuid.UUID, int]] = []
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Case.id, Case.version, Case.kind, Case.status, Case.updated_at).where(
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
        for cid, version, kind_name, status, updated_at in rows:
            kind = CaseKind(kind_name)
            step = STEPS.get((kind, status), (None, None))[0]
            budget = step_budget(settings, kind_name, step.value) if step else 0
            if updated_at > now - timedelta(seconds=budget + 300):
                continue  # the step may still be running
            if step is not None and await failed_runs(session, cid, step.value) >= MAX_TRIES:
                case = await session.get(Case, cid)
                if case is not None:
                    machine = STATUSES[kind]
                    case.status = (
                        for_kind(kind)
                        .transition(machine(case.status), machine("FAILED"), Actor.SYSTEM)
                        .value
                    )
                    case.error = f"{step.value} failed {MAX_TRIES} times; not retried again"
                    log.error("sweep.poison", case_id=str(cid), step=step.value)
                continue
            resumable.append((cid, version))
    for cid, version in resumable:
        await ctx["redis"].enqueue_job("advance", str(cid), _job_id=f"sweep:{cid}:{version}")
    if resumable:
        log.info("sweep.enqueued", cases=len(resumable))
    return len(resumable)
