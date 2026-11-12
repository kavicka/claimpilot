"""Review endpoints for the handler UI.

Values are re-hydrated from the vault here, for the person looking at the claim, and nowhere else
(ADR-003). Every handler action goes through the state machine and lands in the audit log.
"""

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Annotated, Any

import structlog
from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from claimpilot_api.auth import (
    CurrentUser,
    User_,
    clear_session_cookie,
    db,
    hash_password,
    set_session_cookie,
    verify_password,
)
from claimpilot_api.throttle import client_ip, login_throttle
from claimpilot_core.audit import record
from claimpilot_core.db.models import (
    AuditLog,
    Case,
    Claim,
    Correction,
    CoverageDecision,
    DocBlock,
    Document,
    ExtractedField,
    Invoice,
    PipelineStepRun,
    RoutingDecision,
    Summary,
    User,
)
from claimpilot_core.domain import ClaimStatus as S
from claimpilot_core.domain import Queue
from claimpilot_core.fields import normalize as normalize_field
from claimpilot_core.invoice_values import normalize_invoice
from claimpilot_core.pii.tokens import ENTITY_FOR_PREFIX, TOKEN_RE, rehydrate
from claimpilot_core.pii.vault import Vault
from claimpilot_core.policy import load_terms
from claimpilot_core.settings import get_settings, repo_root
from claimpilot_core.state_machine import Actor, InvalidTransitionError, transition

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api")


Session = Annotated[AsyncSession, Depends(db)]


def vault() -> Vault:
    return Vault(get_settings().pii_vault_key.get_secret_value())


# --- auth -----------------------------------------------------------------------------------


class Login(BaseModel):
    username: str
    password: str


DUMMY_HASH = hash_password("timing-equalizer")


@router.post("/auth/login")
async def login(
    body: Login, request: Request, response: Response, session: Session
) -> dict[str, str]:
    redis = getattr(request.app.state, "arq", None)
    ip = client_ip(request, get_settings().trust_forwarded_for)
    if await login_throttle.blocked(redis, body.username, ip):
        raise HTTPException(429, "too many failed logins; try again in 15 minutes")
    user = await session.scalar(select(User).where(User.username == body.username))
    # An unknown user costs the same scrypt as a wrong password, so timing does not tell them apart;
    # a disabled user looks like a wrong password.
    valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not valid or not user.active:
        await login_throttle.failed(redis, body.username, ip)
        raise HTTPException(401, "wrong username or password")
    await login_throttle.succeeded(redis, body.username, ip)
    set_session_cookie(response, user.id)
    return {"username": user.username, "name": user.display_name, "role": user.role}


@router.post("/auth/logout")
async def logout(response: Response) -> dict[str, bool]:
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/auth/me")
async def me(user: User_) -> dict[str, str]:
    if user.role == "agent":
        return {"username": "mcp", "name": "MCP server", "role": "agent"}
    return {"username": user.username, "name": user.name, "role": user.role}


# --- claims -----------------------------------------------------------------------------------


def _total(claim: Claim) -> str | None:
    return (claim.assessment or {}).get("total_payout_eur")


@router.get("/review/claims")
async def queue_view(
    user: User_, session: Session, queue: str | None = None, status: str | None = None
) -> list[dict]:
    q = select(Claim).order_by(Claim.created_at)
    if queue:
        q = q.where(Claim.queue == queue)
    if status:
        q = q.where(Claim.status == status)
    claims = (await session.scalars(q)).all()
    v = vault()
    out = []
    now = datetime.now(UTC)
    for c in claims:
        mapping = {} if user.role == "agent" else await v.load(session, c.id)
        name = mapping.get("<PERSON_1>", "<PERSON_1>" if user.role == "agent" else None)
        out.append(
            {
                "id": str(c.id),
                "reference": c.reference,
                "status": c.status,
                "queue": c.queue,
                "claim_type": c.claim_type,
                "product": c.product,
                "insured": name,
                "claimed_total_eur": (c.facts or {}).get("claimed_total_eur"),
                "payout_eur": _total(c),
                "straight_through": c.straight_through,
                "age_hours": round((now - c.created_at).total_seconds() / 3600, 1),
                "error": c.error,
            }
        )
    return out


@router.get("/review/claims/{claim_id}")
async def claim_detail(claim_id: uuid.UUID, user: User_, session: Session) -> dict:
    claim = await session.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(404, "no such claim")
    # Agents (the MCP server) see tokens, never the values behind them (ADR-003).
    mapping = {} if user.role == "agent" else await vault().load(session, claim.id)

    def show(value: str | None) -> str | None:
        return rehydrate(value, mapping) if value else value

    docs = (
        await session.scalars(
            select(Document).where(Document.case_id == claim.id).order_by(Document.created_at)
        )
    ).all()
    fields = (
        await session.scalars(
            select(ExtractedField)
            .where(ExtractedField.case_id == claim.id)
            .order_by(ExtractedField.id)
        )
    ).all()
    # Text a reader of the document cannot see (white on white, 1 pt, off the page): never sent to
    # a model, shown to the handler with the R10 warning.
    hidden = (
        await session.scalars(
            select(DocBlock)
            .where(DocBlock.document_id.in_([d.id for d in docs]), DocBlock.hidden.is_not(None))
            .order_by(DocBlock.seq)
        )
    ).all()
    routing = (
        await session.scalars(
            select(RoutingDecision)
            .where(RoutingDecision.claim_id == claim.id)
            .order_by(RoutingDecision.id.desc())
        )
    ).first()
    items = (
        await session.scalars(
            select(CoverageDecision)
            .where(CoverageDecision.claim_id == claim.id)
            .order_by(CoverageDecision.id)
        )
    ).all()
    summaries = (
        await session.scalars(
            select(Summary).where(Summary.claim_id == claim.id).order_by(Summary.id)
        )
    ).all()
    steps = (
        await session.scalars(
            select(PipelineStepRun)
            .where(PipelineStepRun.case_id == claim.id)
            .order_by(PipelineStepRun.id)
        )
    ).all()
    audit = (
        await session.scalars(
            select(AuditLog).where(AuditLog.case_id == claim.id).order_by(AuditLog.id)
        )
    ).all()
    trace_id = next((s.trace_id for s in steps if s.trace_id), None)
    lf = get_settings().langfuse_host
    return {
        "id": str(claim.id),
        "reference": claim.reference,
        "status": claim.status,
        "queue": claim.queue,
        "claim_type": claim.claim_type,
        "product": claim.product,
        "policy_number": claim.policy_id,
        "error": claim.error,
        "core_claim_id": claim.core_claim_id,
        "facts": claim.facts,
        "assessment": claim.assessment,
        "needs_reassessment": await needs_reassessment(session, claim.id),
        "version": claim.version,
        "insured": mapping.get("<PERSON_1>"),
        "documents": [
            {
                "id": str(d.id),
                "filename": d.filename,
                "doc_type": d.doc_type,
                "language": d.language,
                "pages": [
                    f"/api/review/documents/{d.id}/pages/{n}"
                    for n in range(1, (d.page_count or 0) + 1)
                ],
                "masking": masking(d.id, d.page_count or 0),
                "fields": [
                    {
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
                    for f in fields
                    if f.document_id == d.id
                ],
                "hidden_text": [
                    {
                        "page": b.page,
                        "bbox": b.bbox,
                        "reason": b.hidden,
                        # Tokens re-hydrated for a handler; an agent gets tokens only.
                        "text": show(b.text_redacted)
                        if b.text_redacted is not None
                        else (None if user.role == "agent" else b.text),
                    }
                    for b in hidden
                    if b.document_id == d.id
                ],
            }
            for d in docs
        ],
        "routing": {
            "queue": routing.queue,
            "rule_hits": routing.rule_hits,
            "llm_used": routing.llm_used,
            "rationale": routing.rationale,
        }
        if routing
        else None,
        "coverage": [
            {
                "ref": i.item_ref,
                "description": show(i.item_description),
                "coverage": i.coverage,
                "verdict": i.verdict,
                "clauses": i.clause_ids,
                "claimed": str(i.claimed_amount) if i.claimed_amount is not None else None,
                "currency": i.claimed_currency,
                "payout_eur": str(i.payout_eur),
                "rationale": show(i.rationale),
            }
            for i in items
        ],
        "summaries": [
            {
                "kind": s.kind,
                "language": s.language,
                "text": show(s.text),
                "fact_violations": s.fact_violations,
            }
            for s in summaries
        ],
        "steps": [
            {
                "step": s.step,
                "status": s.status,
                "attempt": s.attempt,
                "latency_ms": s.latency_ms,
                "tokens": s.tokens_in + s.tokens_out,
                "models": s.models,
                "error": s.error,
            }
            for s in steps
        ],
        "trace_url": f"{lf}/project/claimpilot/traces/{trace_id}" if lf and trace_id else None,
        "audit": [
            {"action": a.action, "details": a.details, "at": a.created_at.isoformat()}
            for a in audit
        ],
    }


def masking(document_id: uuid.UUID, page_count: int) -> dict[str, Any] | None:
    """What masking left for the viewer's Masked view: the masked page urls with counts, or the
    reason it refused. None until the worker wrote it (the extract step or the backfill)."""
    manifest = get_settings().storage_dir / "renders" / str(document_id) / "mask.json"
    try:
        report = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return None
    refused = report.get("refused")
    return {
        "pages": []
        if refused
        else [
            f"/api/review/documents/{document_id}/pages/{n}?masked=true"
            for n in range(1, page_count + 1)
        ],
        "masked_blocks": report.get("masked_blocks", 0),
        "unread_lines": report.get("unread_lines", 0),
        "refused": refused,
    }


@router.get("/review/documents/{document_id}/pages/{page}")
async def page_image(
    document_id: uuid.UUID, page: int, user: User_, masked: bool = False
) -> FileResponse:
    """A page render; `masked=true` gives the copy a cloud model would receive (ADR-010)."""
    if user.role == "agent":
        raise HTTPException(
            403, "page images show personal data; the service account cannot read them"
        )
    name = f"m{page}.png" if masked else f"p{page}.png"
    path = get_settings().storage_dir / "renders" / str(document_id) / name
    if not path.exists():
        raise HTTPException(404, "no render for this page")
    return FileResponse(path, media_type="image/png")


@router.get("/review/clauses/{clause_id}")
async def clause(clause_id: str, user: User_) -> dict[str, str]:
    terms = load_terms(repo_root() / "data" / "policies" / "vpp_cp_2026.yaml")
    try:
        c = terms.clause(clause_id)
    except KeyError as exc:
        raise HTTPException(404, "no such clause") from exc
    return {
        "clause_id": c.clause_id,
        "display": terms.display_id(c.clause_id),
        "heading": c.article_title,
        "text": c.text,
    }


# --- corrections and actions ------------------------------------------------------------------


class FieldEdit(BaseModel):
    value: str
    version: int | None = None  # the claim version the handler saw


def check_version(case: Case, seen: int | None) -> None:
    """A person decides on what they saw: the version of that page is required (428 without it)
    and must still be current (409 if the case changed since)."""
    noun = "claim" if case.kind == "claim" else "invoice"
    if seen is None:
        raise HTTPException(
            428, f"send the {noun} version you saw (the page's `version`); reload and try again"
        )
    if seen != case.version:
        raise HTTPException(
            409, f"the {noun} changed since you opened it; reload to see the current version"
        )


def require_senior_in_senior_queue(case: Case, user: CurrentUser) -> None:
    """Fraud-review and senior cases belong to senior handlers for everything that changes them:
    a plain handler could otherwise correct the field that raised the flag, reassess so the case
    is routed to a normal queue, and approve it there."""
    if case.queue in SENIOR_QUEUES and user.role != "senior":
        noun = "claims" if case.kind == "claim" else "invoices"
        raise HTTPException(403, f"{noun} in this queue need a senior handler")


async def count_corrected(session: AsyncSession, case_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(ExtractedField)
            .where(ExtractedField.case_id == case_id, ExtractedField.corrected.is_(True))
        )
    ) or 0


async def audit_decision(
    session: AsyncSession, case: Case, user: CurrentUser, action: str, body: "ActionBody"
) -> None:
    """The audit row of a handler action: what was decided, on which version of what amount."""
    if isinstance(case, Invoice):
        total, currency = case.total, case.currency
    else:
        total, currency = (getattr(case, "assessment", None) or {}).get("total_payout_eur"), "EUR"
    record(
        session,
        case.id,
        user.id,
        action,
        {
            "note": body.note,
            "total": str(total) if total is not None else None,
            "currency": currency,
            "version": body.version,
            "queue": case.queue,
            "status": case.status,
            "corrected_fields": await count_corrected(session, case.id),
        },
    )


async def enqueue(request: Request, claim_id: uuid.UUID) -> None:
    """The change is committed already; if Redis is down, the worker's sweep picks it up."""
    try:
        arq: ArqRedis = request.app.state.arq
        await arq.enqueue_job("advance", str(claim_id))
    except (OSError, RedisError) as exc:
        log.warning(
            "enqueue failed, left to the sweep", claim_id=str(claim_id), error=type(exc).__name__
        )


PII_FIELD = re.compile(r"name|holder|iban|birth|phone|email|address|passport|plate")
PII_ENTITY = [
    ("iban", "IBAN"),
    ("birth", "BIRTH_NUMBER"),
    ("phone", "PHONE"),
    ("email", "EMAIL_ADDRESS"),
    ("address", "ADDRESS"),
    ("passport", "ID_CARD"),
    ("plate", "LICENCE_PLATE"),
]


def pii_entity(field: str, old_value: str | None) -> str | None:
    """Which PII entity a corrected field holds, so a new value goes to the vault, not the table."""
    if m := TOKEN_RE.search(old_value or ""):
        return ENTITY_FOR_PREFIX[m.group(1)]
    if not PII_FIELD.search(field):
        return None
    return next((entity for key, entity in PII_ENTITY if key in field), "PERSON")


@router.patch("/review/fields/{field_id}")
async def correct_field(
    field_id: int, body: FieldEdit, user: User_, session: Session
) -> dict[str, Any]:
    if user.role == "agent":
        raise HTTPException(403, "agents cannot change claims")
    row = await session.get(ExtractedField, field_id)
    if row is None:
        raise HTTPException(404, "no such field")
    case = await session.get(Case, row.case_id)
    if case is None or case.status != S.IN_REVIEW.value:
        raise HTTPException(409, "fields can be corrected only while the case is in review")
    check_version(case, body.version)
    require_senior_in_senior_queue(case, user)
    invoice = case.kind == "invoice"
    mapping = await vault().load(session, row.case_id)
    reverse = {v: k for k, v in mapping.items()}
    stored = reverse.get(body.value)  # keep tokens for values the vault already holds
    if stored is None:
        # On an invoice, company data (supplier name, IBAN) is not personal: only a value that
        # was a token goes back to the vault.
        entity = pii_entity("", row.value_raw) if invoice else pii_entity(row.field, row.value_raw)
        if entity and body.value.strip():
            stored = await vault().add(session, row.case_id, entity, body.value)
            mapping[stored] = body.value
        else:
            stored = body.value
    session.add(
        Correction(field_id=row.id, old_value=row.value_raw, new_value=stored, user_id=user.id)
    )
    record(
        session,
        row.case_id,
        user.id,
        "correct_field",
        {"field": row.field, "document_id": str(row.document_id), "version": body.version},
    )
    norm = normalize_invoice(row.field, stored) if invoice else normalize_field(row.field, stored)
    row.value_raw, row.value_norm = stored, norm
    row.corrected, row.grounded, row.confidence, row.method = True, True, 1.0, "handler"
    flag_modified(case, "status")  # a correction is a change of the case: bump its version
    await session.commit()
    return {
        "id": row.id,
        "value": rehydrate(stored, mapping),
        "value_norm": row.value_norm,
        "claim_version": case.version,
    }


class ActionBody(BaseModel):
    note: str | None = None
    version: int | None = None  # the claim version the handler saw


ACTIONS = {
    "approve": S.APPROVED,
    "reject": S.REJECTED,
    "request-info": S.NEEDS_INFO,
    "reassess": S.EXTRACTED,
    "retry": S.RECEIVED,  # a failed claim starts over from ingest
}


async def needs_reassessment(session: AsyncSession, claim_id: uuid.UUID) -> bool:
    """A correction made after the last assessment: routing, payout and letters may be stale."""
    last_fix = await session.scalar(
        select(func.max(Correction.created_at))
        .join(ExtractedField, ExtractedField.id == Correction.field_id)
        .where(ExtractedField.case_id == claim_id)
    )
    assessed = await session.scalar(
        select(func.max(CoverageDecision.created_at)).where(CoverageDecision.claim_id == claim_id)
    )
    return last_fix is not None and (assessed is None or last_fix > assessed)


SENIOR_QUEUES = {Queue.SENIOR.value, Queue.FRAUD_REVIEW.value}


@router.post("/review/claims/{claim_id}/actions/{action}")
async def act(
    claim_id: uuid.UUID,
    action: str,
    body: ActionBody,
    user: User_,
    session: Session,
    request: Request,
) -> dict:
    if user.role == "agent":
        raise HTTPException(403, "agents cannot act on claims; a handler approves")
    claim = await session.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(404, "no such claim")
    check_version(claim, body.version)
    require_senior_in_senior_queue(claim, user)
    if action == "escalate":
        if claim.status != S.IN_REVIEW.value:
            raise HTTPException(409, "only claims in review can be escalated")
        claim.queue = Queue.SENIOR.value
    elif action in ACTIONS:
        if action == "approve" and await needs_reassessment(session, claim.id):
            raise HTTPException(409, "fields were corrected after the assessment; reassess first")
        try:
            claim.status = transition(S(claim.status), ACTIONS[action], Actor.HANDLER).value
        except InvalidTransitionError as exc:
            raise HTTPException(409, str(exc)) from exc
        if action == "approve":
            claim.straight_through = not await count_corrected(session, claim.id)
    else:
        raise HTTPException(404, f"unknown action {action}")
    if action == "retry":
        claim.error = None
    await audit_decision(session, claim, user, action, body)
    await session.commit()
    if action in ("approve", "reassess", "retry"):
        await enqueue(request, claim.id)
    return {"status": claim.status, "queue": claim.queue, "version": claim.version}


class Erasure(BaseModel):
    reason: str


@router.delete("/review/claims/{claim_id}")
async def erase(
    claim_id: uuid.UUID, body: Erasure, user: User_, session: Session
) -> dict[str, bool]:
    """Erase one claim end to end (GDPR Art. 17). Senior handlers only."""
    from claimpilot_core.erasure import erase_claim

    if user.role != "senior":
        raise HTTPException(403, "only a senior handler can erase a claim")
    done = await erase_claim(
        session, claim_id, get_settings().storage_dir, reason=body.reason, user_id=user.id
    )
    if not done:
        raise HTTPException(404, "no such claim")
    await session.commit()
    return {"erased": True}


# --- ops and evals ----------------------------------------------------------------------------


@router.get("/review/ops")
async def ops(user: User_, session: Session) -> dict:
    claims = (await session.scalars(select(Claim))).all()
    by_queue: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for c in claims:
        by_queue[c.queue or "none"] = by_queue.get(c.queue or "none", 0) + 1
        by_status[c.status] = by_status.get(c.status, 0) + 1
    runs = (
        await session.scalars(
            select(PipelineStepRun)
            .join(Claim, Claim.id == PipelineStepRun.case_id)
            .where(PipelineStepRun.status == "ok")
        )
    ).all()
    per_claim: dict[uuid.UUID, list[PipelineStepRun]] = {}
    for r in runs:
        per_claim.setdefault(r.case_id, []).append(r)
    latency = sorted(sum(r.latency_ms or 0 for r in rs) for rs in per_claim.values())
    tokens = [sum(r.tokens_in + r.tokens_out for r in rs) for rs in per_claim.values()]
    decided = [c for c in claims if c.status in (S.APPROVED.value, S.SUBMITTED.value)]
    return {
        "claims": len(claims),
        "by_queue": by_queue,
        "by_status": by_status,
        "straight_through_rate": round(sum(c.straight_through for c in decided) / len(decided), 3)
        if decided
        else None,
        "latency_p50_s": round(median(latency) / 1000, 1) if latency else None,
        "latency_p95_s": round(latency[min(len(latency) - 1, int(0.95 * len(latency)))] / 1000, 1)
        if latency
        else None,
        "tokens_per_claim": round(sum(tokens) / len(tokens)) if tokens else None,
        "dead_letter": [
            {"id": str(c.id), "reference": c.reference, "error": c.error}
            for c in claims
            if c.status == S.FAILED.value
        ],
    }


@router.get("/review/evals")
async def evals(user: User_) -> list[dict]:
    reports = repo_root() / "evals" / "reports"
    latest: dict[str, Path] = {}
    for p in sorted(reports.glob("*-dev.json")):
        suite = p.stem.split("-", 1)[1].rsplit("-", 1)[0]
        latest[suite] = p
    out = []
    for suite, p in sorted(latest.items()):
        data = json.loads(p.read_text("utf-8"))
        out.append(
            {
                "suite": suite,
                "created": data["meta"].get("created"),
                "metrics": data["metrics"],
                "ops": data.get("ops", {}),
                "models": data["meta"].get("models"),
                "notes": data.get("notes", [])[:6],
            }
        )
    return out
