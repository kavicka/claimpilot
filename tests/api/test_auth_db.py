"""Identity against the test database: role and active flag come from the database on every
request, the production cookie, the throttle behind the login endpoint, demo users, and the
admin CLI."""

import uuid

import pytest
from apitools import PASSWORD, FakeRedis, decide, login, make_claim, make_user
from sqlalchemy import select

from claimpilot_api import admin, auth
from claimpilot_core.db import session as db_session
from claimpilot_core.db.models import AuditLog, User
from claimpilot_core.settings import get_settings

pytestmark = pytest.mark.db


async def set_user(name, **values) -> None:
    async with db_session.session_scope() as s:
        user = await s.scalar(select(User).where(User.username == name))
        for key, value in values.items():
            setattr(user, key, value)


# --- the database decides, not the cookie ------------------------------------------------------


async def test_a_disabled_user_is_refused_on_the_next_request(client):
    name = await make_user("handler")
    await login(client, name)
    assert (await client.get("/api/auth/me")).status_code == 200
    await set_user(name, active=False)
    assert (await client.get("/api/auth/me")).status_code == 401  # same cookie, no new login
    assert (await client.get("/api/review/claims")).status_code == 401
    # ... and cannot log in again, with the same answer as for a wrong password.
    r = await client.post("/api/auth/login", json={"username": name, "password": PASSWORD})
    assert r.status_code == 401
    wrong = await client.post("/api/auth/login", json={"username": name, "password": "x"})
    assert r.json() == wrong.json()
    await set_user(name, active=True)
    await login(client, name)


async def test_a_disabled_user_cannot_upload_with_an_old_cookie(client):
    name = await make_user("handler")
    await login(client, name)
    await set_user(name, active=False)
    files = [("files", ("a.pdf", b"%PDF-1.4 test"))]
    assert (await client.post("/api/claims", files=files)).status_code == 401


async def test_a_demoted_senior_loses_senior_rights_at_once(client):
    name = await make_user("senior")
    cid, _ = await make_claim(queue="senior")
    await login(client, name)
    assert (await client.get("/api/auth/me")).json()["role"] == "senior"
    await set_user(name, role="handler")
    assert (await client.get("/api/auth/me")).json()["role"] == "handler"
    assert (await decide(client, f"/api/review/claims/{cid}", "approve")).status_code == 403
    erase = await client.request("DELETE", f"/api/review/claims/{cid}", json={"reason": "x"})
    assert erase.status_code == 403


async def test_a_promoted_handler_gets_the_new_role_without_a_new_login(client):
    name = await make_user("handler")
    cid, _ = await make_claim(queue="senior")
    await login(client, name)
    assert (await decide(client, f"/api/review/claims/{cid}", "approve")).status_code == 403
    await set_user(name, role="senior")
    assert (await decide(client, f"/api/review/claims/{cid}", "approve")).status_code == 200


async def test_the_cookie_holds_no_role(client):
    await login(client, "senior.demo")
    raw = auth.base64.urlsafe_b64decode(client.cookies.get(auth.COOKIE)).decode()
    assert "senior" not in raw and raw.count(":") == 2  # user id, issued at, signature


# --- the cookie in production ------------------------------------------------------------------


async def test_the_dev_cookie_works_over_http(client):
    r = await client.post(
        "/api/auth/login", json={"username": "handler.demo", "password": PASSWORD}
    )
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie


async def test_the_production_cookie_is_secure_and_strict(client, monkeypatch):
    monkeypatch.setenv("CLAIMPILOT_ENVIRONMENT", "production")
    monkeypatch.setenv("CLAIMPILOT_SESSION_SECRET", "prod-session-secret-" + "x" * 20)
    get_settings.cache_clear()
    r = await client.post(
        "/api/auth/login", json={"username": "handler.demo", "password": PASSWORD}
    )
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    out = await client.post("/api/auth/logout")
    assert "secure" in out.headers["set-cookie"].lower()


async def test_production_has_no_random_session_secret(client, monkeypatch):
    monkeypatch.setenv("CLAIMPILOT_ENVIRONMENT", "production")
    monkeypatch.delenv("CLAIMPILOT_SESSION_SECRET", raising=False)
    monkeypatch.setenv("CLAIMPILOT_SESSION_SECRET", "")
    get_settings.cache_clear()
    from claimpilot_core.settings import InsecureConfigError

    with pytest.raises(InsecureConfigError):
        auth.sign(uuid.uuid4())


# --- demo users --------------------------------------------------------------------------------


async def test_demo_users_exist_in_dev_only(client, monkeypatch):
    dev, prod = f"demo.dev.{uuid.uuid4().hex[:6]}", f"demo.prod.{uuid.uuid4().hex[:6]}"
    monkeypatch.setenv("CLAIMPILOT_DEMO_PASSWORD", PASSWORD)
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "DEMO_USERS", [(dev, "Dev Demo", "handler")])
    async with db_session.session_scope() as s:
        await auth.ensure_demo_users(s)
    monkeypatch.setenv("CLAIMPILOT_ENVIRONMENT", "production")
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "DEMO_USERS", [(prod, "Prod Demo", "handler")])
    async with db_session.session_scope() as s:
        await auth.ensure_demo_users(s)
    async with db_session.session_scope() as s:
        names = set(
            (await s.scalars(select(User.username).where(User.username.in_([dev, prod])))).all()
        )
    assert names == {dev}


# --- the throttle behind the login endpoint ----------------------------------------------------


async def bad_login(client, user, **headers):
    return await client.post(
        "/api/auth/login", json={"username": user, "password": "x"}, headers=headers
    )


async def test_the_forwarded_address_is_ignored_unless_trusted(client):
    for _ in range(5):
        await bad_login(client, "senior.demo", **{"X-Forwarded-For": "6.6.6.6"})
    r = await bad_login(client, "senior.demo", **{"X-Forwarded-For": "7.7.7.7"})
    assert r.status_code == 429  # a guesser cannot pick a fresh counter by lying


async def test_behind_the_balancer_each_client_address_has_its_own_counter(client, monkeypatch):
    monkeypatch.setenv("CLAIMPILOT_TRUST_FORWARDED_FOR", "true")
    get_settings.cache_clear()
    for _ in range(5):
        await bad_login(client, "senior.demo", **{"X-Forwarded-For": "203.0.113.1"})
    assert (
        await bad_login(client, "senior.demo", **{"X-Forwarded-For": "203.0.113.1"})
    ).status_code == 429
    other = await client.post(
        "/api/auth/login",
        json={"username": "senior.demo", "password": PASSWORD},
        headers={"X-Forwarded-For": "203.0.113.2"},
    )
    assert other.status_code == 200  # the account owner, from another address, is not locked out


async def test_login_counts_in_redis_when_there_is_one(client):
    from claimpilot_api.main import app

    app.state.arq = redis = FakeRedis()
    for _ in range(5):
        await bad_login(client, "senior.demo")
    assert len(redis.data) == 1 and list(redis.data.values()) == [5]
    assert (await bad_login(client, "senior.demo")).status_code == 429


# --- claimpilot-admin --------------------------------------------------------------------------


def cli(*argv):
    return admin.parser().parse_args(["users", *argv])


async def test_admin_adds_lists_disables_and_changes_users(client):
    name = f"anna.{uuid.uuid4().hex[:6]}"
    out = await admin.run(
        cli("add", name, "--name", "Anna Nováková", "--role", "handler"),
        password=lambda: "a-long-enough-password",
    )
    assert out == [f"created {name} (handler)"]
    await login_with(client, name, "a-long-enough-password")

    assert any(
        name in line and "handler" in line and "active" in line
        for line in await admin.run(cli("list"))
    )
    await admin.run(cli("set-role", name, "senior"))
    assert (await client.get("/api/auth/me")).json()["role"] == "senior"

    await admin.run(cli("disable", name))
    assert (await client.get("/api/auth/me")).status_code == 401
    assert any("DISABLED" in line and name in line for line in await admin.run(cli("list")))
    await admin.run(cli("enable", name))
    assert (await client.get("/api/auth/me")).status_code == 200

    await admin.run(cli("set-password", name), password=lambda: "another-long-password")
    bad = await client.post(
        "/api/auth/login", json={"username": name, "password": "a-long-enough-password"}
    )
    assert bad.status_code == 401
    await login_with(client, name, "another-long-password")

    async with db_session.session_scope() as s:
        actions = (
            await s.scalars(
                select(AuditLog.action).where(AuditLog.details["username"].astext == name)
            )
        ).all()
    assert set(actions) == {
        "admin_user_add",
        "admin_user_role",
        "admin_user_disable",
        "admin_user_enable",
        "admin_user_password",
    }


async def login_with(client, name, password):
    r = await client.post("/api/auth/login", json={"username": name, "password": password})
    assert r.status_code == 200, r.text


async def test_admin_refuses_bad_input(client):
    ok = f"bob.{uuid.uuid4().hex[:6]}"
    with pytest.raises(admin.AdminError, match="at least 12"):
        await admin.run(
            cli("add", ok, "--name", "Bob", "--role", "handler"), password=lambda: "short"
        )
    with pytest.raises(admin.AdminError, match="username"):
        await admin.run(
            cli("add", "x y", "--name", "Bob", "--role", "handler"),
            password=lambda: "a-long-enough-password",
        )
    with pytest.raises(admin.AdminError, match="exists"):
        await admin.run(
            cli("add", "handler.demo", "--name", "Dup", "--role", "handler"),
            password=lambda: "a-long-enough-password",
        )
    with pytest.raises(admin.AdminError, match="no such user"):
        await admin.run(cli("disable", "nobody.at.all"))
    with pytest.raises(SystemExit):  # argparse: a role that does not exist
        cli("set-role", "handler.demo", "admin")


def test_the_password_comes_from_the_environment_or_a_prompt_never_argv():
    assert (
        admin.read_password({admin.PASSWORD_ENV: "from-the-environment"}) == "from-the-environment"
    )
    answers = iter(["typed-twice-long", "typed-twice-long"])
    assert admin.read_password({}, ask=lambda _: next(answers)) == "typed-twice-long"
    differ = iter(["one-long-password", "two-long-password"])
    with pytest.raises(admin.AdminError, match="differ"):
        admin.read_password({}, ask=lambda _: next(differ))
    with pytest.raises(admin.AdminError, match="at least 12"):
        admin.read_password({admin.PASSWORD_ENV: "short"})
    assert "--password" not in admin.parser().format_help()
