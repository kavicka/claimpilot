"""Local login with two roles (handler, senior): enough to attribute every action in the audit log.

Sessions are an HMAC-signed cookie. Demo users are created on startup only when
CLAIMPILOT_DEMO_PASSWORD is set (local development only). Without CLAIMPILOT_SESSION_SECRET the api
signs sessions with a random key, so sessions end when it restarts.
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
import uuid
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import User

COOKIE = "cp_session"
TTL_SECONDS = 12 * 3600
DEMO_USERS = [
    ("handler.demo", "Hana Handler", "handler"),
    ("senior.demo", "Samuel Senior", "senior"),
]


log = logging.getLogger(__name__)
_RANDOM_SECRET = secrets.token_bytes(32)


def _secret() -> bytes:
    configured = os.environ.get("CLAIMPILOT_SESSION_SECRET", "")
    return configured.encode() if configured else _RANDOM_SECRET


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


def sign(user_id: uuid.UUID, role: str) -> str:
    body = f"{user_id}:{role}:{int(time.time()) + TTL_SECONDS}"
    mac = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{body}:{mac}".encode()).decode()


def unsign(token: str) -> tuple[uuid.UUID, str] | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        uid, role, exp, mac = raw.split(":")
    except (ValueError, UnicodeDecodeError):
        return None
    expected = hmac.new(_secret(), f"{uid}:{role}:{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected) or int(exp) < time.time():
        return None
    return uuid.UUID(uid), role


async def ensure_demo_users(session: AsyncSession) -> None:
    password = os.environ.get("CLAIMPILOT_DEMO_PASSWORD", "")
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
    def __init__(self, user_id: uuid.UUID, role: str) -> None:
        self.id, self.role = user_id, role


AGENT_ID = uuid.UUID(int=0)


def current_user(
    cp_session: Annotated[str | None, Cookie()] = None,
    x_service_token: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """A handler with a session cookie, or the MCP server with its service token. The service
    account has role "agent": it reads redacted data and can take no action."""
    token = os.environ.get("CLAIMPILOT_MCP_TOKEN", "")
    if x_service_token and token and hmac.compare_digest(x_service_token, token):
        return CurrentUser(AGENT_ID, "agent")
    parsed = unsign(cp_session) if cp_session else None
    if parsed is None:
        raise HTTPException(401, "log in first")
    return CurrentUser(*parsed)


User_ = Annotated[CurrentUser, Depends(current_user)]


def human_user(user: User_) -> CurrentUser:
    if user.role == "agent":
        raise HTTPException(403, "the service account reads redacted data only")
    return user


Human = Annotated[CurrentUser, Depends(human_user)]


def intake(
    cp_session: Annotated[str | None, Cookie()] = None,
    x_intake_token: Annotated[str | None, Header()] = None,
) -> str:
    """Uploads come from the portal (intake token) or from a logged-in handler."""
    token = os.environ.get("CLAIMPILOT_INTAKE_TOKEN", "")
    if x_intake_token and token and hmac.compare_digest(x_intake_token, token):
        return "portal"
    parsed = unsign(cp_session) if cp_session else None
    if parsed is None:
        raise HTTPException(401, "intake token or login required")
    return f"user:{parsed[0]}"


Intake = Annotated[str, Depends(intake)]
