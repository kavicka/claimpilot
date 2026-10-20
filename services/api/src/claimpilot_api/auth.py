"""Login with two roles (handler, senior): enough to attribute every action in the audit log.

The session is an HMAC-signed cookie that names the user and says when it was issued, nothing
else. Every request loads the user from the database, so the role and the `active` flag are the
current ones: a demoted or disabled user loses access on the next request, not when the cookie
expires. Users are managed with `claimpilot-admin`; demo users exist only in dev, and only when
CLAIMPILOT_DEMO_PASSWORD is set.
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import Cookie, Depends, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import User
from claimpilot_core.db.session import get_sessionmaker
from claimpilot_core.settings import InsecureConfigError, get_settings

COOKIE = "cp_session"
TTL_SECONDS = 12 * 3600
DEMO_USERS = [
    ("handler.demo", "Hana Handler", "handler"),
    ("senior.demo", "Samuel Senior", "senior"),
]
ROLES = ("handler", "senior")


log = logging.getLogger(__name__)
_RANDOM_SECRET = secrets.token_bytes(32)


async def db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


Session = Annotated[AsyncSession, Depends(db)]


def _secret() -> bytes:
    settings = get_settings()
    configured = (
        os.environ.get("CLAIMPILOT_SESSION_SECRET", "")
        or settings.session_secret.get_secret_value()
    )
    if configured:
        return configured.encode()
    if settings.environment == "production":
        raise InsecureConfigError("CLAIMPILOT_SESSION_SECRET is empty")
    return _RANDOM_SECRET  # dev: sessions end when the api restarts


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, _ = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, base64.b64decode(salt_b64)), stored)


def sign(user_id: uuid.UUID, issued_at: int | None = None) -> str:
    body = f"{user_id}:{issued_at if issued_at is not None else int(time.time())}"
    mac = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{body}:{mac}".encode()).decode()


def unsign(token: str) -> tuple[uuid.UUID, int] | None:
    """The user id and time of issue, if the signature is ours and the session has not run out."""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        uid, issued, mac = raw.split(":")
        user_id, issued_at = uuid.UUID(uid), int(issued)
    except (ValueError, UnicodeDecodeError):
        return None
    expected = hmac.new(_secret(), f"{uid}:{issued}".encode(), hashlib.sha256).hexdigest()
    now = time.time()
    if (
        not hmac.compare_digest(mac, expected)
        or issued_at + TTL_SECONDS < now
        or issued_at > now + 60
    ):
        return None
    return user_id, issued_at


def _cookie_flags() -> tuple[bool, Literal["lax", "strict"]]:
    """(secure, samesite): production cookies travel over HTTPS only and never cross-site."""
    production = get_settings().environment == "production"
    return production, "strict" if production else "lax"


def set_session_cookie(response: Response, user_id: uuid.UUID) -> None:
    secure, samesite = _cookie_flags()
    response.set_cookie(
        COOKIE, sign(user_id), max_age=TTL_SECONDS, httponly=True, secure=secure, samesite=samesite
    )


def clear_session_cookie(response: Response) -> None:
    secure, samesite = _cookie_flags()
    response.delete_cookie(COOKIE, httponly=True, secure=secure, samesite=samesite)


async def ensure_demo_users(session: AsyncSession) -> None:
    """Dev only. Production has no demo users (and refuses to start if a demo password is set)."""
    settings = get_settings()
    password = settings.demo_password.get_secret_value()
    if settings.environment == "production":
        return
    if not password:
        log.warning("CLAIMPILOT_DEMO_PASSWORD is not set: no demo users created")
        return
    for username, name, role in DEMO_USERS:
        if not await session.scalar(select(User).where(User.username == username)):
            session.add(
                User(
                    username=username,
                    display_name=name,
                    role=role,
                    password_hash=hash_password(password),
                )
            )


class CurrentUser:
    def __init__(self, user_id: uuid.UUID, role: str, username: str = "", name: str = "") -> None:
        self.id, self.role, self.username, self.name = user_id, role, username, name


AGENT_ID = uuid.UUID(int=0)


async def _session_user(session: AsyncSession, cp_session: str | None) -> User | None:
    """The active user the cookie names, as the database has them now."""
    parsed = unsign(cp_session) if cp_session else None
    if parsed is None:
        return None
    user = await session.get(User, parsed[0])
    return user if user is not None and user.active else None


async def current_user(
    session: Session,
    cp_session: Annotated[str | None, Cookie()] = None,
    x_service_token: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """A handler with a session cookie, or the MCP server with its service token. The service
    account has role "agent": it reads redacted data and can take no action. Role and `active`
    come from the database on every request, never from the cookie."""
    token = os.environ.get("CLAIMPILOT_MCP_TOKEN", "")
    if x_service_token and token and hmac.compare_digest(x_service_token, token):
        return CurrentUser(AGENT_ID, "agent")
    user = await _session_user(session, cp_session)
    if user is None:
        raise HTTPException(401, "log in first")
    return CurrentUser(user.id, user.role, user.username, user.display_name)


User_ = Annotated[CurrentUser, Depends(current_user)]


def human_user(user: User_) -> CurrentUser:
    if user.role == "agent":
        raise HTTPException(403, "the service account reads redacted data only")
    return user


Human = Annotated[CurrentUser, Depends(human_user)]


async def intake(
    session: Session,
    cp_session: Annotated[str | None, Cookie()] = None,
    x_intake_token: Annotated[str | None, Header()] = None,
) -> str:
    """Uploads come from the portal (intake token) or from a logged-in handler."""
    token = os.environ.get("CLAIMPILOT_INTAKE_TOKEN", "")
    if x_intake_token and token and hmac.compare_digest(x_intake_token, token):
        return "portal"
    user = await _session_user(session, cp_session)
    if user is None:
        raise HTTPException(401, "intake token or login required")
    return f"user:{user.id}"


Intake = Annotated[str, Depends(intake)]
