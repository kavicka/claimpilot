"""`/ready`: is the system able to do work, and how much is waiting?

`/health` (main.py) only says the api process and its database answer; compose and the ALB use it
and its meaning does not change. `/ready` adds Redis and the worker's heartbeat and reports counts:
the cases in FAILED and the length of the job queue. It answers 503 when a component is down, so a
monitor can alert on the status code and read the detail from the body.

The worker writes its heartbeat through arq (`health_check_interval`, 30 s); the key lives for the
interval plus one second, so a key that exists is at most that old. The age reported is derived
from the key's remaining time.
"""

import asyncio
from typing import Any

from arq.constants import default_queue_name, health_check_key_suffix
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from claimpilot_core.db.models import Case
from claimpilot_core.db.session import get_sessionmaker
from claimpilot_core.settings import WORKER_HEARTBEAT_INTERVAL_S, get_settings

router = APIRouter()
CHECK_TIMEOUT_S = 3  # a component that does not answer is down
HEARTBEAT_KEY = default_queue_name + health_check_key_suffix


def _down(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": type(exc).__name__}  # the type only: messages can hold URLs


async def _database() -> dict[str, Any]:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S), get_sessionmaker()() as session:
            failed = await session.scalar(
                select(func.count()).select_from(Case).where(Case.status == "FAILED")
            )
        return {"ok": True, "failed_cases": failed or 0}
    except Exception as exc:
        return _down(exc)


async def _redis(request: Request) -> dict[str, Any]:
    try:
        redis = request.app.state.arq
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            await redis.ping()
            return {"ok": True, "queue_length": await redis.zcard(default_queue_name)}
    except Exception as exc:
        return _down(exc)


async def _worker(request: Request) -> dict[str, Any]:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            ttl_ms = await request.app.state.arq.pttl(HEARTBEAT_KEY)
    except Exception as exc:
        return _down(exc)
    if ttl_ms is None or ttl_ms < 0:  # -2: no key, -1: key without expiry (not ours)
        return {"ok": False, "error": "no heartbeat"}
    age = max(0.0, WORKER_HEARTBEAT_INTERVAL_S + 1 - ttl_ms / 1000)
    return {
        "ok": age < get_settings().ready_worker_max_age_s,
        "heartbeat_age_s": round(age, 1),
    }


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    components = {
        "database": await _database(),
        "redis": await _redis(request),
        "worker": await _worker(request),
    }
    up = all(c["ok"] for c in components.values())
    return JSONResponse(
        status_code=200 if up else 503,
        content={"status": "ok" if up else "unavailable", "components": components},
    )
