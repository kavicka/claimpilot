"""The api when Redis is down, and a handler retrying a failed claim."""

import pymupdf
import pytest
from apitools import decide, login, make_claim
from redis.exceptions import ConnectionError as RedisConnectionError

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import Claim

pytestmark = pytest.mark.db


class DownArq:
    async def enqueue_job(self, *args, **kwargs):
        raise RedisConnectionError("Connection refused")

    # The rate limit and the login throttle use Redis too: both let the request through.
    incr = expire = get = set = delete = enqueue_job


async def test_upload_and_approval_survive_a_redis_outage(client):
    """The change is committed before the enqueue; the worker's sweep picks the claim up later."""
    from claimpilot_api.main import app

    app.state.arq = DownArq()
    doc = pymupdf.open()
    doc.new_page()
    r = await client.post(
        "/api/claims",
        files=[("files", ("a.pdf", doc.tobytes()))],
        headers={"X-Intake-Token": "intake-token"},
    )
    assert r.status_code == 201
    async with db_session.session_scope() as s:
        assert (await s.get(Claim, r.json()["id"])).status == "RECEIVED"
    cid, _ = await make_claim()
    await login(client)
    r = await decide(client, f"/api/review/claims/{cid}", "approve")
    assert r.json()["status"] == "APPROVED"


async def test_handler_retries_a_failed_claim(client):
    from claimpilot_api.main import app

    cid, _ = await make_claim(status="FAILED")
    async with db_session.session_scope() as s:
        (await s.get(Claim, cid)).error = "ConnectError: connection refused"
    await login(client)
    r = await decide(client, f"/api/review/claims/{cid}", "retry")
    assert r.json()["status"] == "RECEIVED"
    assert ("advance", (str(cid),)) in app.state.arq.jobs
    async with db_session.session_scope() as s:
        assert (await s.get(Claim, cid)).error is None
    # Only a failed claim can be retried.
    cid2, _ = await make_claim()
    r = await decide(client, f"/api/review/claims/{cid2}", "retry")
    assert r.status_code == 409
