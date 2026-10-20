"""The ECS health check of the worker reads arq's heartbeat key."""

from claimpilot_worker import healthcheck


class Redis:
    def __init__(self, keys: set[str]) -> None:
        self.keys = keys

    def exists(self, key: str) -> int:
        return int(key in self.keys)


def test_alive_while_the_heartbeat_key_exists():
    assert healthcheck.alive(Redis({"arq:queue:health-check"}))
    assert not healthcheck.alive(Redis(set()))


def test_the_key_is_the_one_arq_writes():
    from claimpilot_worker.main import WorkerSettings

    # arq: queue_name + ":health-check"; the default queue is "arq:queue"
    assert getattr(WorkerSettings, "queue_name", "arq:queue") + ":health-check" == (
        healthcheck.HEARTBEAT_KEY
    )


def test_an_unreachable_redis_fails_the_check(monkeypatch):
    monkeypatch.setenv("CLAIMPILOT_REDIS_URL", "redis://127.0.0.1:1/0")
    from claimpilot_core.settings import get_settings

    get_settings.cache_clear()
    try:
        assert healthcheck.main() == 1
    finally:
        get_settings.cache_clear()
