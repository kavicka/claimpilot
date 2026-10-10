"""Run the arq worker and start it again when Redis goes away.

arq's worker exits as soon as it loses its Redis connection. In Phase 1 the worker runs natively
without a process manager, so this loop is its supervisor; on ECS (Phase 2) the service restarts
the task instead.

    uv run claimpilot-worker
"""

import time

import structlog
from arq.worker import run_worker
from redis.exceptions import RedisError

from claimpilot_core.logging import configure_logging

log = structlog.get_logger(__name__)
BACKOFF_S = (2, 5, 10, 30, 60)


def main() -> None:
    from claimpilot_worker.main import WorkerSettings

    configure_logging("INFO")
    failures = 0
    while True:
        started = time.monotonic()
        try:
            run_worker(WorkerSettings)  # type: ignore[arg-type]
            return  # stopped with Ctrl-C or SIGTERM
        except (RedisError, OSError) as exc:
            if time.monotonic() - started > 300:
                failures = 0  # it ran fine for a while; this is a new outage
            wait = BACKOFF_S[min(failures, len(BACKOFF_S) - 1)]
            failures += 1
            log.warning("worker.redis_lost", error=type(exc).__name__, restart_in_s=wait)
            time.sleep(wait)


if __name__ == "__main__":
    main()
