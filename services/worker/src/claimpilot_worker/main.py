"""arq worker. Runs natively on macOS in Phase 1 so Docling, the reranker and NER get MPS.

make worker   # uv run arq claimpilot_worker.main.WorkerSettings
"""

from typing import Any, ClassVar

import structlog
from arq import cron
from arq.connections import RedisSettings

import claimpilot_worker.steps  # noqa: F401 - registers the pipeline steps
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.logging import configure_logging
from claimpilot_core.settings import get_settings, longest_step_budget
from claimpilot_worker.pipeline import MAX_TRIES, advance, safe_error, sweep

log = structlog.get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging("INFO")
    ctx["settings"] = get_settings()
    ctx["gateway"] = LLMGateway(ctx["settings"])
    await ensure_index(ctx["gateway"])
    await sweep(ctx)  # resume claims whose jobs were lost while the worker was down


async def ensure_index(gateway: LLMGateway) -> None:
    """Build the coverage index from the VPP PDF on first start."""
    from sqlalchemy import func, select

    from claimpilot_core.db.models import PolicyChunk
    from claimpilot_core.db.session import session_scope
    from claimpilot_core.settings import repo_root
    from claimpilot_worker.coverage.index import build_index

    async with session_scope() as session:
        if not await session.scalar(select(func.count()).select_from(PolicyChunk)):
            await build_index(
                session, repo_root() / "data" / "policies" / "vpp_cp_2026.pdf", gateway
            )


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["gateway"].aclose()


async def ping(_ctx: dict[str, Any]) -> str:
    return "pong"


async def purge(ctx: dict[str, Any]) -> int:
    """Daily: erase finished claims past the retention period; for invoices, erase personal data
    when it is due and delete the whole case once the accounting period is over (ADR-016)."""
    from claimpilot_core import erasure
    from claimpilot_core.db.session import session_scope
    from claimpilot_core.retention import invoice_retention

    settings = ctx["settings"]
    policy = invoice_retention(settings.config_dir)
    async with session_scope() as session:
        claims = await erasure.expired_claims(session, retention_days=settings.retention_days)
        deletions = await erasure.invoices_due_deletion(session, policy)
        personal = [
            i
            for i in await erasure.invoices_due_personal_erasure(session, policy)
            if i not in set(deletions)
        ]
    work = (
        [("claim", c, "retention period ended") for c in claims]
        + [("invoice-data", i, "personal data retention ended") for i in personal]
        + [("invoice", i, "accounting retention ended") for i in deletions]
    )
    done = 0
    for what, cid, reason in work:
        try:
            async with session_scope() as session:  # one case per transaction: one bad case
                if what == "claim":  # does not hold back the others
                    await erasure.erase_claim(session, cid, settings.storage_dir, reason=reason)
                elif what == "invoice-data":
                    await erasure.erase_invoice_personal_data(
                        session, cid, settings.storage_dir, reason=reason
                    )
                else:
                    await erasure.erase_case(session, cid, settings.storage_dir, reason=reason)
            done += 1
        except Exception as exc:
            log.error("purge.failed", case_id=str(cid), what=what, error=safe_error(exc))
    return done


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping, advance, purge, sweep]
    cron_jobs: ClassVar[list[Any]] = [
        cron(purge, hour={3}, minute={15}),
        cron(sweep, minute={0, 10, 20, 30, 40, 50}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 1  # one claim step at a time: the models share one GPU
    max_tries = MAX_TRIES
    # arq writes a heartbeat key this often; /ready and the ECS health check read it. Cron jobs and
    # steps run on the same event loop, so a step that blocks it for minutes stops the heartbeat.
    health_check_interval = 30
    # Every step has its own time budget (pipeline.advance, settings.step_timeouts) that fires
    # first and moves the case to FAILED. This limit only catches what escapes the budget: it
    # sits above the longest one. A job lost with a crashed worker is retried after it, or found
    # by the sweep.
    job_timeout = longest_step_budget(get_settings()) + 120
