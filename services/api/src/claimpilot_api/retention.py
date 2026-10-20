"""Erasure on request for invoices (ADR-016): personal data goes, the accounting record stays.

Claims are erased whole through `DELETE /api/review/claims/{id}`. An invoice is an accounting
document, so a request removes the people in it (vault, page text, the uploaded file, notes) and
the case itself is deleted only when its accounting period is over (the worker's daily purge).
"""

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from claimpilot_api.auth import User_
from claimpilot_api.review import Session
from claimpilot_core.db.models import Case
from claimpilot_core.erasure import CLOSED_INVOICE, erase_invoice_personal_data
from claimpilot_core.settings import get_settings

router = APIRouter(prefix="/api/review")


class PersonalDataErasure(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.delete("/invoices/{invoice_id}/personal-data")
async def erase_invoice_data(
    invoice_id: uuid.UUID, body: PersonalDataErasure, user: User_, session: Session
) -> dict[str, bool]:
    """Senior handlers only. Allowed once the invoice is exported, rejected, or has stopped."""
    if user.role != "senior":
        raise HTTPException(403, "only a senior handler can erase personal data")
    status = await session.scalar(
        select(Case.status).where(Case.id == invoice_id, Case.kind == "invoice")
    )
    if status is None:
        raise HTTPException(404, "no such invoice")
    if status not in CLOSED_INVOICE:
        raise HTTPException(409, "the invoice is still being processed; decide it first")
    await erase_invoice_personal_data(
        session, invoice_id, get_settings().storage_dir, reason=body.reason, user_id=user.id
    )
    await session.commit()
    return {"erased": True}
