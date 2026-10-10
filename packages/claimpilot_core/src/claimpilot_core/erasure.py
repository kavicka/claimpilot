"""Retention and erasure (GDPR Art. 17, DPIA-lite in docs/governance).

`erase_claim` removes one claim end to end: database rows (cascade), the vault entries behind its
tokens, uploaded files and page renders. Earlier audit lines of the claim keep only the action and
the user; a new line records the erasure with the claim's reference and the reason. Langfuse traces
hold only redacted text; once the vault entries are gone, their tokens point to nothing.
"""

import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import AuditLog, Claim, Document, VaultEntry

FINISHED = ("SUBMITTED", "REJECTED")


async def erase_claim(
    session: AsyncSession,
    claim_id: uuid.UUID,
    storage: Path,
    *,
    reason: str,
    user_id: uuid.UUID | None = None,
) -> bool:
    claim = await session.get(Claim, claim_id)
    if claim is None:
        return False
    doc_ids = (
        await session.scalars(select(Document.id).where(Document.claim_id == claim_id))
    ).all()
    reference = claim.reference
    await session.execute(delete(VaultEntry).where(VaultEntry.claim_id == claim_id))
    # Handlers' notes may name the client: keep that an action happened, drop what was written.
    await session.execute(
        update(AuditLog)
        .where(AuditLog.claim_id == claim_id)
        .values(details={"erased": True}, claim_id=None)
    )
    session.expunge(claim)
    # SQL delete, so the database's ON DELETE CASCADE removes documents, blocks, fields, decisions,
    # summaries and step runs in one statement.
    await session.execute(delete(Claim).where(Claim.id == claim_id))
    shutil.rmtree(storage / "claims" / str(claim_id), ignore_errors=True)
    for doc_id in doc_ids:
        shutil.rmtree(storage / "renders" / str(doc_id), ignore_errors=True)
    session.add(
        AuditLog(
            claim_id=None,
            user_id=user_id,
            action="erasure",
            details={"reference": reference, "reason": reason},
        )
    )
    return True


async def expired_claims(session: AsyncSession, *, retention_days: int) -> list[uuid.UUID]:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    rows = await session.scalars(
        select(Claim.id).where(Claim.status.in_(FINISHED), Claim.created_at < cutoff)
    )
    return list(rows)
