"""arq worker. Runs natively on macOS in Phase 1 so Docling, the reranker and NER get MPS.

make worker   # uv run arq claimpilot_worker.main.WorkerSettings
"""

from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

import claimpilot_worker.steps  # noqa: F401 - registers the pipeline steps
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.logging import configure_logging
from claimpilot_core.settings import check_production, get_settings
from claimpilot_worker.pipeline import MAX_TRIES, advance, sweep


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging("INFO")
    check_production(get_settings(), "worker")  # raises before the first job
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
    """Daily: erase finished claims past the retention period."""
    from claimpilot_core.db.session import session_scope
    from claimpilot_core.erasure import erase_claim, expired_claims

    settings = ctx["settings"]
    async with session_scope() as session:
        ids = await expired_claims(session, retention_days=settings.retention_days)
        for cid in ids:
            await erase_claim(session, cid, settings.storage_dir, reason="retention period ended")
    return len(ids)


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
    # The longest step (extraction of a five-document claim with scans) takes about 5 minutes. A
    # job lost with a crashed worker is retried once this has passed, or found by the sweep.
    job_timeout = 900
