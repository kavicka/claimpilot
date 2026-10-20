"""One place that writes audit rows, so every actor and every action is recorded the same way."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import AuditLog


def record(
    session: AsyncSession,
    case_id: uuid.UUID | None,
    actor: uuid.UUID | None,
    action: str,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """Add an audit row to the session; it is committed with the caller's transaction. `actor` is
    the user id, or None for the system."""
    row = AuditLog(case_id=case_id, user_id=actor, action=action[:32], details=detail or {})
    session.add(row)
    return row
