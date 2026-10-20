"""Two handlers, or a handler and the worker, writing the same claim at the same time."""

import asyncio

import pytest
from apitools import decide, login, make_claim
from sqlalchemy.orm.exc import StaleDataError

from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import Claim

pytestmark = pytest.mark.db


async def seen_version(client, cid):
    return (await client.get(f"/api/review/claims/{cid}")).json()["version"]


def approve(client, cid, **body):
    return client.post(f"/api/review/claims/{cid}/actions/approve", json=body)


async def test_double_approve_registers_once(client):
    from claimpilot_api.main import app

    cid, _ = await make_claim()
    await login(client)
    v = await seen_version(client, cid)
    rs = await asyncio.gather(approve(client, cid, version=v), approve(client, cid, version=v))
    assert sorted(r.status_code for r in rs) == [200, 409]
    assert app.state.arq.jobs.count(("advance", (str(cid),))) == 1


async def test_correction_and_approval_at_once_cannot_both_win(client):
    cid, fid = await make_claim()
    await login(client)
    v = await seen_version(client, cid)
    fix = client.patch(f"/api/review/fields/{fid}", json={"value": "Jana Nováková", "version": v})
    rs = await asyncio.gather(fix, approve(client, cid, version=v))
    assert sorted(r.status_code for r in rs) == [200, 409]
    async with db_session.session_scope() as s:
        claim = await s.get(Claim, cid)
    if rs[1].status_code == 200:  # approved first: the correction was refused
        assert claim.status == "APPROVED"
    else:  # corrected first: approval waits for a reassessment
        assert claim.status == "IN_REVIEW"


async def test_approving_a_version_you_did_not_see_is_refused(client):
    cid, fid = await make_claim()
    await login(client)
    seen = (await client.get(f"/api/review/claims/{cid}")).json()["version"]
    await login(client, "senior.demo")
    await client.post(f"/api/review/claims/{cid}/actions/escalate", json={"version": seen})
    await login(client)
    r = await approve(client, cid, version=seen)  # the handler's page still shows the old claim
    assert r.status_code == 409
    assert "reload" in r.json()["detail"]
    r = await client.patch(f"/api/review/fields/{fid}", json={"value": "x", "version": seen})
    assert r.status_code == 409


async def test_every_change_bumps_the_version(client):
    cid, fid = await make_claim()
    await login(client)
    v0 = (await client.get(f"/api/review/claims/{cid}")).json()["version"]
    r = await client.patch(
        f"/api/review/fields/{fid}", json={"value": "Jana Nováková", "version": v0}
    )
    assert r.json()["claim_version"] == v0 + 1
    r = await client.post(f"/api/review/claims/{cid}/actions/reassess", json={"version": v0 + 1})
    assert r.json()["version"] == v0 + 2


async def test_worker_and_handler_writes_do_not_overwrite_each_other(client):
    """The worker loaded the claim, a handler changed it, then the worker writes: it must fail
    (and retry with fresh data) instead of silently undoing the handler's change."""
    cid, _ = await make_claim()
    async with db_session.session_scope() as worker:
        stale = await worker.get(Claim, cid)
        await login(client)
        r = await decide(client, f"/api/review/claims/{cid}", "escalate")
        assert r.status_code == 200
        stale.error = "worker note"
        with pytest.raises(StaleDataError):
            await worker.flush()
        await worker.rollback()
    async with db_session.session_scope() as s:
        claim = await s.get(Claim, cid)
        assert (claim.queue, claim.error) == ("senior", None)
