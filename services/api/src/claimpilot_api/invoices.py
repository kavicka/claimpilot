"""Review endpoints for supplier invoices: queue, detail with every cell's source, actions.

Invoices hold company data, readable as extracted; people's names, e-mails and phones are tokens,
re-hydrated here for the handler and never for the agent (ADR-003). Every action goes through the
invoice state machine and lands in the audit log; nothing reaches the ERP without an approval.
"""

import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from claimpilot_api.auth import User_
from claimpilot_api.review import (
    ActionBody,
    Session,
    audit_decision,
    check_version,
    enqueue,
    require_senior_in_senior_queue,
    vault,
)
from claimpilot_core.approval import FourEyes, load_four_eyes
from claimpilot_core.db.models import (
    AuditLog,
    Correction,
    DocBlock,
    DocCell,
    Document,
    ExtractedField,
    Invoice,
    PipelineStepRun,
)
from claimpilot_core.domain import InvoiceStatus as S
from claimpilot_core.domain import Queue
from claimpilot_core.pii.tokens import rehydrate
from claimpilot_core.settings import get_settings
from claimpilot_core.state_machine import Actor, InvalidTransitionError, invoices

router = APIRouter(prefix="/api/review")

ACTIONS = {
    "approve": S.APPROVED,
    "reject": S.REJECTED,
    "request-info": S.NEEDS_INFO,
    "reassess": S.EXTRACTED,  # validation, matching and routing run again on the corrections
    "retry": S.RECEIVED,
}
LINE = re.compile(r"lines\[(\d+)\]\.(.+)")


@lru_cache
def _four_eyes(config_dir: Path) -> FourEyes:
    return load_four_eyes(config_dir)


async def correctors(session: Session, invoice_id: uuid.UUID) -> set[uuid.UUID]:
    """Everyone who corrected a field of this invoice."""
    rows = await session.scalars(
        select(Correction.user_id)
        .join(ExtractedField, ExtractedField.id == Correction.field_id)
        .where(ExtractedField.case_id == invoice_id)
        .distinct()
    )
    return set(rows.all())


def _header_value(fields: list[ExtractedField], name: str) -> str | None:
    return next((f.value_raw for f in fields if f.field == name), None)


@router.get("/invoices")
async def invoice_queue(
    user: User_, session: Session, queue: str | None = None, status: str | None = None
) -> list[dict]:
    q = select(Invoice).order_by(Invoice.created_at)
    if queue:
        q = q.where(Invoice.queue == queue)
    if status:
        q = q.where(Invoice.status == status)
    rows = (await session.scalars(q)).all()
    names = {
        f.case_id: f.value_raw
        for f in (
            await session.scalars(
                select(ExtractedField).where(
                    ExtractedField.case_id.in_([r.id for r in rows]),
                    ExtractedField.field == "supplier_name",
                )
            )
        ).all()
    }
    now = datetime.now(UTC)
    return [
        {
            "id": str(r.id),
            "reference": r.reference,
            "status": r.status,
            "queue": r.queue,
            "kind": r.doc_kind,
            "supplier": names.get(r.id),
            "invoice_number": r.invoice_number,
            "total": str(r.total) if r.total is not None else None,
            "currency": r.currency,
            "findings": len((r.matching or {}).get("findings", []))
            + sum(1 for c in r.validation or [] if not c["ok"]),
            "rule": (r.routing or [{}])[0].get("rule") if r.routing else None,
            "age_hours": round((now - r.created_at).total_seconds() / 3600, 1),
            "error": r.error,
        }
        for r in rows
    ]


async def needs_revalidation(session: Session, invoice_id: uuid.UUID) -> bool:
    """A correction made after the last validation: checks, matching and queue may be stale."""
    last_fix = await session.scalar(
        select(func.max(Correction.created_at))
        .join(ExtractedField, ExtractedField.id == Correction.field_id)
        .where(ExtractedField.case_id == invoice_id)
    )
    validated = await session.scalar(
        select(func.max(PipelineStepRun.finished_at)).where(
            PipelineStepRun.case_id == invoice_id,
            PipelineStepRun.step == "validate",
            PipelineStepRun.status == "ok",
        )
    )
    return last_fix is not None and (validated is None or last_fix > validated)


@router.get("/invoices/{invoice_id}")
async def invoice_detail(invoice_id: uuid.UUID, user: User_, session: Session) -> dict:
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "no such invoice")
    mapping = {} if user.role == "agent" else await vault().load(session, inv.id)

    def show(value: str | None) -> str | None:
        return rehydrate(value, mapping) if value else value

    doc = (
        await session.scalars(
            select(Document).where(Document.case_id == inv.id).order_by(Document.created_at)
        )
    ).first()
    fields = (
        await session.scalars(
            select(ExtractedField)
            .where(ExtractedField.case_id == inv.id)
            .order_by(ExtractedField.id)
        )
    ).all()

    def out(f: ExtractedField) -> dict[str, Any]:
        return {
            "id": f.id,
            "field": f.field,
            "value": show(f.value_raw),
            "value_norm": show(f.value_norm),
            "quote": show(f.source_quote),
            "page": f.page,
            "bbox": f.bbox,
            "grounded": f.grounded,
            "confidence": f.confidence,
            "checks": f.checks,
            "corrected": f.corrected,
        }

    header = [out(f) for f in fields if not LINE.match(f.field)]
    lines: dict[int, dict[str, Any]] = defaultdict(dict)
    for f in fields:
        if m := LINE.match(f.field):
            lines[int(m[1])][m[2]] = out(f)
    hidden, cells = [], []
    if doc is not None:
        hidden = (
            await session.scalars(
                select(DocBlock).where(DocBlock.document_id == doc.id, DocBlock.hidden.is_not(None))
            )
        ).all()
        cells = (await session.scalars(select(DocCell).where(DocCell.document_id == doc.id))).all()
    # The box of each item row on the page, so the line table can point at it.
    rows: dict[int, dict[str, Any]] = {}
    item_number = {k: n for n, k in enumerate(sorted({(c.tbl, c.item) for c in cells}), start=1)}
    for c in cells:
        n = item_number[(c.tbl, c.item)]
        box = rows.get(n, {"page": c.page, "bbox": dict(c.bbox)})
        if box["page"] == c.page:
            b = box["bbox"]
            box["bbox"] = {
                "x0": min(b["x0"], c.bbox["x0"]),
                "y0": min(b["y0"], c.bbox["y0"]),
                "x1": max(b["x1"], c.bbox["x1"]),
                "y1": max(b["y1"], c.bbox["y1"]),
            }
        rows[n] = box
    steps = (
        await session.scalars(
            select(PipelineStepRun)
            .where(PipelineStepRun.case_id == inv.id)
            .order_by(PipelineStepRun.id)
        )
    ).all()
    audit = (
        await session.scalars(
            select(AuditLog).where(AuditLog.case_id == inv.id).order_by(AuditLog.id)
        )
    ).all()
    return {
        "id": str(inv.id),
        "reference": inv.reference,
        "status": inv.status,
        "queue": inv.queue,
        "kind": inv.doc_kind,
        "invoice_number": inv.invoice_number,
        "total": str(inv.total) if inv.total is not None else None,
        "currency": inv.currency,
        "error": inv.error,
        "version": inv.version,
        "needs_revalidation": await needs_revalidation(session, inv.id),
        "document": {
            "id": str(doc.id),
            "filename": doc.filename,
            "pages": [
                f"/api/review/documents/{doc.id}/pages/{n}"
                for n in range(1, (doc.page_count or 0) + 1)
            ],
            "hidden_text": [
                {
                    "page": b.page,
                    "bbox": b.bbox,
                    "reason": b.hidden,
                    "text": show(b.text_redacted) if b.text_redacted is not None else None,
                }
                for b in hidden
            ],
        }
        if doc
        else None,
        "header": header,
        "lines": [
            {"n": n, "row": rows.get(n), "fields": lines[n]} for n in sorted(set(lines) | set(rows))
        ],
        "validation": inv.validation or [],
        "matching": inv.matching,
        "routing": inv.routing or [],
        "erp_id": inv.erp_id,
        "export": inv.export,
        "steps": [
            {
                "step": s.step,
                "status": s.status,
                "latency_ms": s.latency_ms,
                "models": s.models,
                "error": s.error,
            }
            for s in steps
        ],
        "audit": [
            {"action": a.action, "details": a.details, "at": a.created_at.isoformat()}
            for a in audit
        ],
    }


@router.get("/invoices/{invoice_id}/ubl")
async def invoice_ubl(invoice_id: uuid.UUID, user: User_) -> FileResponse:
    """The Peppol UBL document last sent to the ERP."""
    path = get_settings().storage_dir / "invoices" / str(invoice_id) / "export.xml"
    if not path.exists():
        raise HTTPException(404, "nothing was exported yet")
    return FileResponse(path, media_type="application/xml", filename=f"{invoice_id}.xml")


@router.post("/invoices/{invoice_id}/actions/{action}")
async def invoice_action(
    invoice_id: uuid.UUID,
    action: str,
    body: ActionBody,
    user: User_,
    session: Session,
    request: Request,
) -> dict:
    if user.role == "agent":
        raise HTTPException(403, "agents cannot act on invoices; a handler approves")
    inv = await session.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "no such invoice")
    check_version(inv, body.version)
    require_senior_in_senior_queue(inv, user)  # every action, reassess and retry included
    if action == "escalate":
        if inv.status != S.IN_REVIEW.value:
            raise HTTPException(409, "only invoices in review can be escalated")
        inv.queue = Queue.SENIOR.value
    elif action in ACTIONS:
        if action == "approve":
            if await needs_revalidation(session, inv.id):
                raise HTTPException(409, "fields were corrected after validation; reassess first")
            rule = _four_eyes(get_settings().config_dir)
            if rule.applies(inv.total, inv.currency) and user.id in await correctors(
                session, inv.id
            ):
                raise HTTPException(
                    403,
                    "you corrected fields of this invoice and its amount needs a second approver; "
                    "another handler must approve it",
                )
        try:
            inv.status = invoices.transition(S(inv.status), ACTIONS[action], Actor.HANDLER).value
        except InvalidTransitionError as exc:
            raise HTTPException(409, str(exc)) from exc
    else:
        raise HTTPException(404, f"unknown action {action}")
    if action == "retry":
        inv.error = None
    await audit_decision(session, inv, user, action, body)
    await session.commit()
    if action in ("approve", "reassess", "retry"):
        await enqueue(request, inv.id)
    return {"status": inv.status, "queue": inv.queue, "version": inv.version}
