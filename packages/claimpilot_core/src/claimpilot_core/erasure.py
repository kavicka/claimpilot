"""Retention and erasure (GDPR Art. 17, DPIA-lite in docs/governance, ADR-016 for invoices).

Claims: `erase_claim` removes one claim end to end: database rows (cascade), the vault entries
behind its tokens, uploaded files and page renders. Earlier audit lines of the claim keep only the
action and the user; a new line records the erasure with the claim's reference and the reason.

Invoices have two steps, because the invoice record is an accounting document:
  1. `erase_invoice_personal_data`: the vault entries, the page text, the uploaded file and its
     renders, and the handlers' free-text notes go; the header, the lines, the audit trail and
     export.xml stay.
  2. `erase_case`: once the accounting period is over, the case and all its files go.

Langfuse traces hold only redacted text; once the vault entries are gone, their tokens point to
nothing.
"""

import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import (
    AuditLog,
    Case,
    Claim,
    DocBlock,
    DocCell,
    Document,
    VaultEntry,
)
from claimpilot_core.domain import CaseKind
from claimpilot_core.retention import InvoiceRetention, accounting_end, earliest_accounting_end

FINISHED = ("SUBMITTED", "REJECTED")
# Invoice states that end the work on an invoice. NEEDS_INFO and FAILED are not final, but an
# invoice nobody has touched for `personal_data_days` is abandoned and treated like a final one.
CLOSED_INVOICE = ("EXPORTED", "REJECTED", "NEEDS_INFO", "FAILED")
PERSONAL_DATA_ERASED = "personal_data_erased"
_FOLDER = {CaseKind.CLAIM.value: "claims", CaseKind.INVOICE.value: "invoices"}


async def erase_case(
    session: AsyncSession,
    case_id: uuid.UUID,
    storage: Path,
    *,
    reason: str,
    user_id: uuid.UUID | None = None,
    kind: CaseKind | None = None,
) -> bool:
    """Delete a claim or an invoice with everything under it. `kind` restricts what may go."""
    case = await session.get(Case, case_id)
    if case is None or (kind is not None and case.kind != kind.value):
        return False
    doc_ids = (await session.scalars(select(Document.id).where(Document.case_id == case_id))).all()
    reference, folder = case.reference, _FOLDER[case.kind]
    await session.execute(delete(VaultEntry).where(VaultEntry.case_id == case_id))
    # Handlers' notes may name the client: keep that an action happened, drop what was written.
    await session.execute(
        update(AuditLog)
        .where(AuditLog.case_id == case_id)
        .values(details={"erased": True}, case_id=None)
    )
    session.expunge(case)
    # SQL delete, so the database's ON DELETE CASCADE removes documents, blocks, fields, decisions,
    # summaries and step runs in one statement. The case row goes, and its claim or invoice row
    # with it.
    await session.execute(delete(Case).where(Case.id == case_id))
    shutil.rmtree(storage / folder / str(case_id), ignore_errors=True)
    for doc_id in doc_ids:
        shutil.rmtree(storage / "renders" / str(doc_id), ignore_errors=True)
    session.add(
        AuditLog(
            case_id=None,
            user_id=user_id,
            action="erasure",
            details={"reference": reference, "reason": reason},
        )
    )
    return True


async def erase_claim(
    session: AsyncSession,
    claim_id: uuid.UUID,
    storage: Path,
    *,
    reason: str,
    user_id: uuid.UUID | None = None,
) -> bool:
    return await erase_case(
        session, claim_id, storage, reason=reason, user_id=user_id, kind=CaseKind.CLAIM
    )


async def expired_claims(session: AsyncSession, *, retention_days: int) -> list[uuid.UUID]:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    rows = await session.scalars(
        select(Claim.id).where(Claim.status.in_(FINISHED), Claim.created_at < cutoff)
    )
    return list(rows)


# --- invoices ---------------------------------------------------------------------------------


async def erase_invoice_personal_data(
    session: AsyncSession,
    invoice_id: uuid.UUID,
    storage: Path,
    *,
    reason: str,
    user_id: uuid.UUID | None = None,
) -> bool:
    """Step 1 of an invoice's retention: remove what identifies people, keep the accounting
    record. Does not touch the case row, so its `updated_at` (the retention clock) stays."""
    row = (
        await session.execute(
            select(Case.reference).where(Case.id == invoice_id, Case.kind == "invoice")
        )
    ).first()
    if row is None:
        return False
    if await session.scalar(
        select(
            exists().where(AuditLog.case_id == invoice_id, AuditLog.action == PERSONAL_DATA_ERASED)
        )
    ):
        return True  # done before; nothing new can have appeared on a closed invoice
    docs = (await session.execute(select(Document).where(Document.case_id == invoice_id))).scalars()
    docs = list(docs)
    doc_ids = [d.id for d in docs]
    await session.execute(delete(VaultEntry).where(VaultEntry.case_id == invoice_id))
    # The parser's text holds the names; the redacted form holds tokens. Text that never got a
    # redacted form (a failure before redaction) cannot be told from a name, so it goes.
    for model in (DocBlock, DocCell):
        await session.execute(
            update(model)
            .where(model.document_id.in_(doc_ids))
            .values(text=_redacted_or_empty(model))
        )
    for doc in docs:
        _remove_upload(storage, doc.storage_path)
        shutil.rmtree(storage / "renders" / str(doc.id), ignore_errors=True)
        doc.filename = f"erased{Path(doc.storage_path).suffix}"[:256]
    notes = await session.scalars(
        select(AuditLog).where(AuditLog.case_id == invoice_id, AuditLog.details.has_key("note"))
    )
    for line in notes:
        line.details = {
            **{k: v for k, v in line.details.items() if k != "note"},
            "note_erased": True,
        }
    session.add(
        AuditLog(
            case_id=invoice_id,
            user_id=user_id,
            action=PERSONAL_DATA_ERASED,
            details={"reference": row.reference, "reason": reason},
        )
    )
    return True


def _redacted_or_empty(model: type[DocBlock] | type[DocCell]):
    return func.coalesce(model.text_redacted, "")


def _remove_upload(storage: Path, relative: str) -> None:
    """Delete one stored upload; never a path that leaves the storage directory."""
    target = (storage / relative).resolve()
    if target.is_relative_to(storage.resolve()) and target.is_file():
        target.unlink()


async def invoices_due_personal_erasure(
    session: AsyncSession, policy: InvoiceRetention, *, now: datetime | None = None
) -> list[uuid.UUID]:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=policy.personal_data_days)
    done = exists().where(AuditLog.case_id == Case.id, AuditLog.action == PERSONAL_DATA_ERASED)
    rows = await session.scalars(
        select(Case.id).where(
            Case.kind == "invoice",
            Case.status.in_(CLOSED_INVOICE),
            Case.updated_at < cutoff,
            ~done,
        )
    )
    return list(rows)


async def invoices_due_deletion(
    session: AsyncSession, policy: InvoiceRetention, *, now: datetime | None = None
) -> list[uuid.UUID]:
    """Closed invoices whose accounting period is over (calendar-year rule, ADR-016)."""
    now = now or datetime.now(UTC)
    rows = await session.execute(
        select(Case.id, Case.updated_at).where(
            Case.kind == "invoice",
            Case.status.in_(CLOSED_INVOICE),
            Case.updated_at < earliest_accounting_end(now, policy.invoice_years),
        )
    )
    return [cid for cid, closed in rows if accounting_end(closed, policy.invoice_years) <= now]
