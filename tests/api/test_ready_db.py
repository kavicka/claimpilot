"""/ready reports database, Redis and the worker's heartbeat; /health keeps its old meaning."""

import uuid

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import delete

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import Case, Claim

pytestmark = pytest.mark.db


def arq_of(client):
    return client._transport.app.state.arq


async def test_ready_when_everything_is_up(client):
    arq_of(client).queue_length = 4
    r = await client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["components"]["redis"] == {"ok": True, "queue_length": 4}
    assert body["components"]["worker"]["ok"] is True
    assert body["components"]["worker"]["heartbeat_age_s"] < 5
    assert body["components"]["database"]["ok"] is True


async def test_ready_counts_failed_cases_without_turning_unhealthy(client):
    async with db_session.session_scope() as s:
        claim = Claim(reference=f"R-{uuid.uuid4().hex[:8]}", status="FAILED")
        s.add(claim)
        await s.flush()
        cid = claim.id
    try:
        body = (await client.get("/ready")).json()
        assert body["components"]["database"]["failed_cases"] >= 1
        assert body["status"] == "ok"
    finally:  # the shared test database also feeds other tests' counts
        async with db_session.session_scope() as s:
            await s.execute(delete(Case).where(Case.id == cid))


async def test_no_heartbeat_means_the_worker_is_down(client):
    arq_of(client).heartbeat_ttl_ms = -2  # the key does not exist
    r = await client.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["components"]["worker"] == {"ok": False, "error": "no heartbeat"}
    assert body["components"]["redis"]["ok"] and body["components"]["database"]["ok"]


async def test_an_old_heartbeat_is_down(client, monkeypatch):
    from claimpilot_core.settings import get_settings

    monkeypatch.setenv("CLAIMPILOT_READY_WORKER_MAX_AGE_S", "20")
    get_settings.cache_clear()
    arq_of(client).heartbeat_ttl_ms = 5_000  # 31 s lifetime, 5 s left: 26 s old
    r = await client.get("/ready")
    assert r.status_code == 503
    assert r.json()["components"]["worker"]["ok"] is False


async def test_redis_down_is_reported_by_type_only(client):
    async def down(*_a):
        raise RedisConnectionError("redis://:secret@10.0.0.1:6379 refused")

    arq = arq_of(client)
    arq.ping, arq.pttl = down, down
    r = await client.get("/ready")
    assert r.status_code == 503
    comps = r.json()["components"]
    assert comps["redis"] == {"ok": False, "error": "ConnectionError"}
    assert comps["worker"]["ok"] is False
    assert "secret" not in r.text


async def test_health_still_checks_only_the_database(client):
    arq_of(client).heartbeat_ttl_ms = -2
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
