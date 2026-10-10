"""Sessions that were tampered with or expired, the service account on write endpoints, intake
tokens, and login guessing."""

import base64
import time
import uuid

import pytest
from apitools import PASSWORD, login, make_claim

from claimpilot_api import auth

pytestmark = pytest.mark.db
SERVICE = {"X-Service-Token": "svc-token"}


async def me(client, cookie):
    client.cookies.set(auth.COOKIE, cookie)
    return await client.get("/api/auth/me")


async def test_a_cookie_with_a_changed_role_is_rejected(client):
    await login(client, "handler.demo")
    raw = base64.urlsafe_b64decode(client.cookies.get(auth.COOKIE)).decode()
    uid, _role, exp, mac = raw.split(":")
    forged = base64.urlsafe_b64encode(f"{uid}:senior:{exp}:{mac}".encode()).decode()
    assert (await me(client, forged)).status_code == 401


async def test_an_expired_cookie_is_rejected(client, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1_000_000.0)  # signed long ago
    old = auth.sign(uuid.uuid4(), "senior")
    monkeypatch.undo()
    assert (await me(client, old)).status_code == 401


async def test_a_cookie_signed_with_another_secret_is_rejected(client, monkeypatch):
    monkeypatch.setenv("CLAIMPILOT_SESSION_SECRET", "attacker-secret")
    forged = auth.sign(uuid.uuid4(), "senior")
    monkeypatch.setenv("CLAIMPILOT_SESSION_SECRET", "server-secret")
    assert (await me(client, forged)).status_code == 401


@pytest.mark.parametrize("garbage", ["", "x", "not:base64", base64.b64encode(b"a:b").decode()])
async def test_garbage_cookies_are_rejected(client, garbage):
    assert (await me(client, garbage)).status_code == 401


@pytest.mark.parametrize(
    "action", ["approve", "reject", "request-info", "escalate", "reassess", "retry"]
)
async def test_the_service_account_cannot_act(client, action):
    cid, _ = await make_claim()
    r = await client.post(f"/api/review/claims/{cid}/actions/{action}", json={}, headers=SERVICE)
    assert r.status_code == 403


async def test_the_service_account_cannot_erase_or_upload(client):
    cid, _ = await make_claim()
    r = await client.request(
        "DELETE", f"/api/review/claims/{cid}", json={"reason": "x"}, headers=SERVICE
    )
    assert r.status_code == 403
    r = await client.post("/api/claims", files=[("files", ("a.pdf", b"%PDF-"))], headers=SERVICE)
    assert r.status_code == 401


@pytest.mark.parametrize("token", ["wrong", "", "intake-token "])
async def test_uploads_need_the_exact_intake_token(client, token):
    r = await client.post(
        "/api/claims", files=[("files", ("a.pdf", b"%PDF-"))], headers={"X-Intake-Token": token}
    )
    assert r.status_code == 401


async def test_unknown_user_and_wrong_password_look_the_same(client):
    a = await client.post("/api/auth/login", json={"username": "nobody", "password": "x"})
    b = await client.post("/api/auth/login", json={"username": "handler.demo", "password": "x"})
    assert (a.status_code, a.json()) == (b.status_code, b.json()) == (401, a.json())


async def test_password_guessing_is_slowed_down(client):
    for _ in range(5):
        r = await client.post("/api/auth/login", json={"username": "senior.demo", "password": "x"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"username": "senior.demo", "password": PASSWORD})
    assert r.status_code == 429  # even the right password waits out the window
    # Another account is not affected.
    assert (
        await client.post(
            "/api/auth/login", json={"username": "handler.demo", "password": PASSWORD}
        )
    ).status_code == 200


async def test_logout_ends_the_session(client):
    await login(client)
    await client.post("/api/auth/logout")
    assert (await client.get("/api/review/claims")).status_code == 401
