"""Claim context from the database: extractions rebuilt from stored fields, policy data, duplicates.

Steps after extraction work on what was stored, so a handler's correction feeds every later step.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import Claim, DocBlock, Document, ExtractedField
from claimpilot_core.domain import Coverage, DocType, ExtractionMethod, Product
from claimpilot_core.schemas.parsing import Block, FracBox, PageInfo, ParsedDocument
from claimpilot_worker.extraction.extract import Extraction, Field
from claimpilot_worker.ingest.injection_signals import Signal, document_signals
from claimpilot_worker.routing.facts import DocInput, History


@dataclass
class StoredDoc:
    row: Document
    doc: DocInput


async def load_docs(session: AsyncSession, claim_id: uuid.UUID) -> list[StoredDoc]:
    docs = (
        await session.scalars(
            select(Document).where(Document.case_id == claim_id).order_by(Document.created_at)
        )
    ).all()
    out = []
    for d in docs:
        rows = (
            await session.scalars(
                select(ExtractedField)
                .where(ExtractedField.document_id == d.id)
                .order_by(ExtractedField.id)
            )
        ).all()
        fields = [
            Field(
                r.field,
                r.value_raw,
                r.source_quote,
                r.page,
                None,
                r.grounded,
                r.value_norm,
                dict(r.checks or {}),
                r.confidence,
            )
            for r in rows
        ]
        model = rows[0].model if rows else ""
        ex = (
            Extraction(
                DocType(d.doc_type),
                fields,
                {},
                rows[0].prompt_version if rows else None,
                model or "",
                ExtractionMethod(rows[0].method) if rows else ExtractionMethod.LLM_TEXT,
            )
            if d.doc_type
            else None
        )
        blocks = (
            await session.scalars(
                select(DocBlock).where(DocBlock.document_id == d.id).order_by(DocBlock.seq)
            )
        ).all()
        text = "\n".join(b.text_redacted or "" for b in blocks if not b.hidden)
        out.append(
            StoredDoc(
                d,
                DocInput(
                    DocType(d.doc_type) if d.doc_type else DocType.CLAIM_FORM,
                    ex,
                    d.sha256,
                    text,
                    signals_of(list(blocks)),
                ),
            )
        )
    return out


def signals_of(rows: list[DocBlock]) -> list[Signal]:
    """Prompt-injection signals of a stored document, on its redacted text."""
    parsed = ParsedDocument(
        sha256="",
        mime_type="",
        pages=[PageInfo(page=p, width=1, height=1) for p in sorted({r.page for r in rows})],
        blocks=[
            Block(
                page=r.page,
                seq=r.seq,
                kind=r.kind,
                text=r.text_redacted or "",
                bbox=FracBox(**r.bbox),
                hidden=r.hidden,
            )
            for r in rows
        ],
    )
    return document_signals(parsed, {})


async def history_for(session: AsyncSession, claim_id: uuid.UUID) -> History:
    """Files and invoice numbers submitted with other claims before this one. Supplier invoices
    are other cases, not other claims: their numbers must not look like a reused receipt."""
    h = History()
    rows = (
        await session.execute(
            select(Document.sha256, Document.case_id)
            .join(Claim, Claim.id == Document.case_id)
            .where(Document.case_id != claim_id)
        )
    ).all()
    for sha, cid in rows:
        h.files.setdefault(sha, str(cid))
    inv = (
        await session.execute(
            select(ExtractedField.value_norm, ExtractedField.case_id)
            .join(Claim, Claim.id == ExtractedField.case_id)
            .where(ExtractedField.field == "invoice_number", ExtractedField.case_id != claim_id)
        )
    ).all()
    for number, cid in inv:
        if number:
            h.invoices.setdefault(number.strip().upper(), str(cid))
    return h


def first(docs: list[DocInput], doc_type: DocType) -> Extraction | None:
    return next((d.extraction for d in docs if d.doc_type is doc_type and d.extraction), None)


def to_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def product_of(docs: list[DocInput], policy: dict[str, Any] | None) -> Product | None:
    cert = first(docs, DocType.POLICY_CERTIFICATE)
    name = (cert.value("product_name") or "").lower() if cert else ""
    for p in Product:
        if p.value in name:
            return p
    return Product(policy["product"]) if policy else None


def periods(
    docs: list[DocInput], policy: dict[str, Any] | None
) -> tuple[tuple[date, date] | None, tuple[date, date] | None]:
    cert = first(docs, DocType.POLICY_CERTIFICATE)
    start = to_date(cert.value("policy_start")) if cert else None
    end = to_date(cert.value("policy_end")) if cert else None
    if not (start and end) and policy:
        start, end = to_date(policy["start"]), to_date(policy["end"])
    form = first(docs, DocType.CLAIM_FORM)
    ts, te = (
        (to_date(form.value("trip_start")), to_date(form.value("trip_end")))
        if form
        else (None, None)
    )
    return ((start, end) if start and end else None), ((ts, te) if ts and te else None)


def issued_on(docs: list[DocInput], policy: dict[str, Any] | None) -> date | None:
    """When the policy was issued: the certificate, else the policy register."""
    cert = first(docs, DocType.POLICY_CERTIFICATE)
    issued = to_date(cert.value("issue_date")) if cert else None
    return issued or (to_date(policy.get("issue_date")) if policy else None)


def delay_hours(docs: list[DocInput]) -> int | None:
    pir = first(docs, DocType.PROPERTY_IRREGULARITY_REPORT)
    if not pir or not pir.value("arrival_time") or not pir.value("delivery_time"):
        return None
    try:
        a = datetime.fromisoformat(pir.value("arrival_time") or "")
        b = datetime.fromisoformat(pir.value("delivery_time") or "")
    except ValueError:
        return None
    return int((b - a).total_seconds() // 3600)


def prior_paid(policy: dict[str, Any] | None) -> dict[Coverage, Decimal]:
    if not policy:
        return {}
    return {Coverage(k): Decimal(str(v)) for k, v in policy.get("prior_paid", {}).items()}
