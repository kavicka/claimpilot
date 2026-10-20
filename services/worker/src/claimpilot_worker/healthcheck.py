"""Container health check of the worker (ECS `healthCheck`): exit 0 while arq's heartbeat exists.

    python -m claimpilot_worker.healthcheck

arq writes the key every `health_check_interval` seconds (30) and lets it expire a second after
that, so a missing key means the worker stopped, lost Redis, or its event loop is blocked. The
module imports no pipeline code: it must start in well under a second.
"""

import sys
from typing import Any

from arq.constants import default_queue_name, health_check_key_suffix

HEARTBEAT_KEY = default_queue_name + health_check_key_suffix


def alive(client: Any) -> bool:  # a redis.Redis, or anything with exists(key)
    return bool(client.exists(HEARTBEAT_KEY))


def main() -> int:
    import redis

    from claimpilot_core.settings import get_settings

    client = redis.Redis.from_url(get_settings().redis_url, socket_timeout=5)
    try:
        return 0 if alive(client) else 1
    except redis.RedisError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
