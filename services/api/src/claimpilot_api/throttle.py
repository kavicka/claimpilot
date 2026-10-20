"""Login throttle: failed logins per (username, client address).

Counters live in Redis with a TTL, so every api task sees the same count and nothing grows without
bound. If Redis is down (or the client is not a Redis client) a bounded in-process LRU counts
instead: per task, but the throttle never turns off.
"""

import contextlib
import hashlib
import time
from collections import OrderedDict
from typing import Any

from fastapi import Request
from redis.exceptions import RedisError

MAX_FAILED, WINDOW_S = 5, 15 * 60
MAX_ENTRIES = 10_000


def client_ip(request: Request | Any, trust_forwarded_for: bool) -> str:
    """The TCP peer, or, behind our load balancer, the address it appended to X-Forwarded-For.

    That is the last entry, not the first: the balancer keeps whatever the client sent and adds
    the peer it saw, so the first entry is the client's to choose and would let a guesser use a
    fresh counter on every attempt."""
    if trust_forwarded_for:
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
        hops = [h for h in hops if h]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"


class LoginThrottle:
    def __init__(
        self, max_failed: int = MAX_FAILED, window_s: int = WINDOW_S, max_entries: int = MAX_ENTRIES
    ) -> None:
        self.max_failed, self.window_s, self.max_entries = max_failed, window_s, max_entries
        self._memory: OrderedDict[str, list[float]] = OrderedDict()

    def clear(self) -> None:
        self._memory.clear()

    @staticmethod
    def _key(username: str, ip: str) -> str:
        digest = hashlib.sha256(f"{username.strip().lower()}|{ip}".encode()).hexdigest()
        return f"cp:login-fail:{digest[:32]}"  # no username or address in Redis

    @staticmethod
    def _usable(redis: Any) -> bool:
        return redis is not None and hasattr(redis, "incr")

    async def blocked(self, redis: Any, username: str, ip: str) -> bool:
        key = self._key(username, ip)
        if self._usable(redis):
            try:
                return int(await redis.get(key) or 0) >= self.max_failed
            except (RedisError, OSError):
                pass
        return len(self._recent(key)) >= self.max_failed

    async def failed(self, redis: Any, username: str, ip: str) -> None:
        key = self._key(username, ip)
        if self._usable(redis):
            try:
                if await redis.set(key, 1, ex=self.window_s, nx=True):
                    return
                if await redis.incr(key) == 1:  # the key expired in between: give it a TTL again
                    await redis.expire(key, self.window_s)
                return
            except (RedisError, OSError):
                pass
        self._memory[key] = [*self._recent(key), time.monotonic()]
        self._memory.move_to_end(key)
        while len(self._memory) > self.max_entries:
            self._memory.popitem(last=False)

    async def succeeded(self, redis: Any, username: str, ip: str) -> None:
        key = self._key(username, ip)
        self._memory.pop(key, None)
        if self._usable(redis):
            with contextlib.suppress(RedisError, OSError):
                await redis.delete(key)

    def _recent(self, key: str) -> list[float]:
        now = time.monotonic()
        return [t for t in self._memory.get(key, []) if now - t < self.window_s]


login_throttle = LoginThrottle()
