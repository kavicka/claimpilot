"""`claimpilot-admin`: user administration for the review UI.

    claimpilot-admin users add anna.novakova --name "Anna Nováková" --role handler
    claimpilot-admin users list
    claimpilot-admin users disable anna.novakova      # also: enable
    claimpilot-admin users set-role anna.novakova senior
    claimpilot-admin users set-password anna.novakova

A password is asked for on the terminal (twice) or taken from CLAIMPILOT_ADMIN_NEW_PASSWORD; it is
never an argument, so it stays out of the shell history and the process list. A disabled user is
refused on the next request. Every change lands in the audit log.
"""

import argparse
import asyncio
import getpass
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_api.auth import ROLES, hash_password
from claimpilot_core.audit import record
from claimpilot_core.db.models import User
from claimpilot_core.db.session import session_scope

PASSWORD_ENV = "CLAIMPILOT_ADMIN_NEW_PASSWORD"  # noqa: S105 - a variable name
MIN_PASSWORD = 12
USERNAME = re.compile(r"[A-Za-z0-9._@-]{3,64}")


class AdminError(Exception):
    """Something the administrator can fix; printed without a traceback."""


def check_password(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        raise AdminError(f"the password needs at least {MIN_PASSWORD} characters")
    return password


def check_role(role: str) -> str:
    if role not in ROLES:
        raise AdminError(f"the role is one of: {', '.join(ROLES)}")
    return role


async def _get(session: AsyncSession, username: str) -> User:
    user = await session.scalar(select(User).where(User.username == username))
    if user is None:
        raise AdminError(f"no such user: {username}")
    return user


def _audit(session: AsyncSession, action: str, username: str, **detail: object) -> None:
    record(session, None, None, action, {"username": username, "by": _operator(), **detail})


def _operator() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


async def add_user(
    session: AsyncSession, username: str, display_name: str, role: str, password: str
) -> User:
    if not USERNAME.fullmatch(username):
        raise AdminError("the username is 3-64 characters: letters, digits, . _ @ -")
    check_role(role)
    check_password(password)
    if not display_name.strip():
        raise AdminError("give the user a name with --name")
    if await session.scalar(select(User).where(User.username == username)):
        raise AdminError(f"the user {username} exists already")
    user = User(
        username=username,
        display_name=display_name.strip(),
        role=role,
        password_hash=hash_password(password),
        active=True,
    )
    session.add(user)
    await session.flush()
    _audit(session, "admin_user_add", username, role=role)
    return user


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.username))).all())


async def set_active(session: AsyncSession, username: str, active: bool) -> User:
    user = await _get(session, username)
    user.active = active
    _audit(session, "admin_user_enable" if active else "admin_user_disable", username)
    return user


async def set_role(session: AsyncSession, username: str, role: str) -> User:
    check_role(role)
    user = await _get(session, username)
    previous, user.role = user.role, role
    _audit(session, "admin_user_role", username, role=role, previous=previous)
    return user


async def set_password(session: AsyncSession, username: str, password: str) -> User:
    check_password(password)
    user = await _get(session, username)
    user.password_hash = hash_password(password)
    _audit(session, "admin_user_password", username)
    return user


def read_password(
    env: Mapping[str, str] | None = None, ask: Callable[[str], str] = getpass.getpass
) -> str:
    """From CLAIMPILOT_ADMIN_NEW_PASSWORD, or asked twice on the terminal."""
    env = os.environ if env is None else env
    if env.get(PASSWORD_ENV):
        return check_password(env[PASSWORD_ENV])
    if not sys.stdin.isatty() and ask is getpass.getpass:
        raise AdminError(f"no terminal to ask on: set {PASSWORD_ENV}")
    first = ask("New password: ")
    if first != ask("Repeat it: "):
        raise AdminError("the two passwords differ")
    return check_password(first)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claimpilot-admin", description=(__doc__ or "").split("\n\n")[0]
    )
    top = p.add_subparsers(dest="group", required=True)
    users = top.add_parser("users", help="manage the users of the review UI")
    cmd = users.add_subparsers(dest="command", required=True)
    add = cmd.add_parser("add", help="create a user (password from the terminal or the env var)")
    add.add_argument("username")
    add.add_argument("--name", required=True, help="the name shown in the UI and the audit log")
    add.add_argument("--role", required=True, choices=ROLES)
    cmd.add_parser("list", help="list users")
    for name, text in (("disable", "refuse the user from the next request"), ("enable", "undo it")):
        cmd.add_parser(name, help=text).add_argument("username")
    role = cmd.add_parser("set-role", help="change a user's role, effective on the next request")
    role.add_argument("username")
    role.add_argument("role", choices=ROLES)
    cmd.add_parser("set-password", help="set a new password").add_argument("username")
    return p


async def run(args: argparse.Namespace, password: Callable[[], str] = read_password) -> list[str]:
    """Execute one command; returns the lines to print."""
    async with session_scope() as session:
        match args.command:
            case "add":
                user = await add_user(session, args.username, args.name, args.role, password())
                return [f"created {user.username} ({user.role})"]
            case "list":
                return [
                    f"{u.username:24} {u.role:8} {'active' if u.active else 'DISABLED':9} "
                    f"{u.display_name}"
                    for u in await list_users(session)
                ]
            case "disable" | "enable":
                user = await set_active(session, args.username, args.command == "enable")
                return [f"{user.username}: {'active' if user.active else 'disabled'}"]
            case "set-role":
                user = await set_role(session, args.username, args.role)
                return [f"{user.username}: {user.role}"]
            case "set-password":
                await set_password(session, args.username, password())
                return [f"{args.username}: password changed"]
    raise AdminError("unknown command")


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        lines = asyncio.run(run(args))
    except AdminError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
