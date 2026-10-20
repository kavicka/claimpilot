"""Intake hardening: a fixed-window rate limit per intake identity, and storing uploads so that a
failed commit leaves no file behind."""

import contextlib
import time
from pathlib import Path

import structlog
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.settings import get_settings

log = structlog.get_logger(__name__)
WINDOW_S = 60
MAX_CLAIM_FILES = 20  # main.MAX_FILES
MULTIPART_SLACK = 1024 * 1024  # boundaries, field names, the scenario id


async def enforce_rate_limit(request: Request, source: str) -> None:
    """At most `intake_rate_per_min` uploads per minute for each intake identity (the portal's
    token, or a logged-in user). Counted in Redis so every api task shares one counter. Redis
    being down does not stop intake: the sweep and the queue need it anyway, and refusing every
    client would turn a Redis blip into an outage of the portal."""
    limit = get_settings().intake_rate_per_min
    if limit <= 0:
        return
    now = int(time.time())
    key = f"claimpilot:intake:{source}:{now // WINDOW_S}"
    try:
        redis = request.app.state.arq
        count = await redis.incr(key)
        await redis.expire(key, 2 * WINDOW_S)
    except RedisError as exc:
        log.warning("intake.ratelimit_unavailable", error=type(exc).__name__)
        return
    if count > limit:
        raise HTTPException(
            429,
            f"too many uploads: at most {limit} per minute",
            headers={"Retry-After": str(WINDOW_S - now % WINDOW_S)},
        )


async def store_and_commit(
    session: AsyncSession, storage: Path, files: list[tuple[str, bytes]]
) -> None:
    """Write the uploads (path relative to `storage`, bytes), then commit. If anything fails, the
    files written so far are removed and the transaction is rolled back, so no orphan stays."""
    written: list[Path] = []
    try:
        for relative, data in files:
            target = storage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            written.append(target)
            target.write_bytes(data)
        await session.commit()
    except BaseException:
        await session.rollback()
        for target in written:
            target.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                target.parent.rmdir()  # the case's folder, when it is empty now
        raise


async def reject_oversized(request: Request, call_next):
    """Refuse an upload by its Content-Length before the multipart body is read and spooled to
    disk. The per-file check in the endpoints stays: a client can leave the header out."""
    path = request.url.path
    if request.method == "POST" and path in ("/api/invoices", "/api/claims"):
        mb = get_settings().max_upload_mb
        files = MAX_CLAIM_FILES if path == "/api/claims" else 1
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > mb * 1024 * 1024 * files + MULTIPART_SLACK:
            return JSONResponse({"detail": f"the upload is larger than {mb} MB"}, status_code=413)
    return await call_next(request)
