"""arq worker. Runs natively on macOS in Phase 1 so Docling, the reranker and NER get MPS.

make worker   # uv run arq claimpilot_worker.main.WorkerSettings
"""

from typing import Any, ClassVar

from arq.connections import RedisSettings

from claimpilot_core.logging import configure_logging
from claimpilot_core.settings import get_settings


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging("INFO")
    ctx["settings"] = get_settings()


async def shutdown(ctx: dict[str, Any]) -> None:
    pass


async def ping(_ctx: dict[str, Any]) -> str:
    return "pong"


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 2
    job_timeout = 900
