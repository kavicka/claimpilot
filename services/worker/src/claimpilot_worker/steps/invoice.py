"""Invoice steps: RECEIVED -> PARSED -> REDACTED -> EXTRACTED -> VALIDATED -> MATCHED ->
ROUTED -> IN_REVIEW, and after approval APPROVED -> EXPORTED.

Missing pages (validation) and a credit note whose original is unknown (matching) go to
NEEDS_INFO instead.

An invoice case holds one document: the invoice, credit note or proforma. Ingest parses it with
its item table (doc_cells); redaction tokenizes people's data and keeps company data readable;
extraction stores the header fields under their names and line values as "lines[N].<field>".
"""

import re
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import DocBlock, DocCell, Document, ExtractedField, Invoice
from claimpilot_core.domain import CaseKind, ExtractionMethod, PipelineStep
from claimpilot_core.domain import InvoiceStatus as S
from claimpilot_core.invoice_values import parse_number
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.pii.vault import Vault
from claimpilot_core.schemas.parsing import Block, FracBox, PageInfo, ParsedDocument, TableCell
from claimpilot_worker.export.ubl import build as build_ubl
from claimpilot_worker.export.values import ExportError, from_values
from claimpilot_worker.extraction.invoice import extract_invoice, invoice_kind, redact_invoice
from claimpilot_worker.ingest.check import problem_of
from claimpilot_worker.ingest.injection_signals import document_signals
from claimpilot_worker.ingest.language import detect_language
from claimpilot_worker.ingest.parser import parse
from claimpilot_worker.ingest.renders import render_pages
from claimpilot_worker.matching.invoice import match
from claimpilot_worker.matching.settings import match_settings
from claimpilot_worker.pipeline import register
from claimpilot_worker.routing.invoice import route_invoice
from claimpilot_worker.steps.common import storage_path
from claimpilot_worker.validation.invoice import validate
from claimpilot_worker.validation.settings import config, ours, tolerance

INVOICE = CaseKind.INVOICE


async def _document(session: AsyncSession, invoice: Invoice) -> Document:
    doc = (
        await session.scalars(
            select(Document).where(Document.case_id == invoice.id).order_by(Document.created_at)
        )
    ).first()
    if doc is None:
        raise RuntimeError(f"invoice {invoice.id} has no document")
    return doc


@register(S.RECEIVED, PipelineStep.INGEST, kind=INVOICE)
async def ingest(session: AsyncSession, invoice: Invoice, ctx: dict[str, Any]) -> S:
    doc = await _document(session, invoice)
    path = storage_path(doc.storage_path)
    problem = problem_of(path)
    doc.problem = problem.detail if problem else None
    if problem:
        return S.NEEDS_INFO
    parsed = parse(path, tables=True)
    await session.execute(delete(DocBlock).where(DocBlock.document_id == doc.id))
    await session.execute(delete(DocCell).where(DocCell.document_id == doc.id))
    for b in parsed.blocks:
        session.add(
            DocBlock(
                document_id=doc.id,
                page=b.page,
                seq=b.seq,
                kind=b.kind,
                text=b.text,
                bbox=b.bbox.model_dump(),
                ocr=b.ocr,
                hidden=b.hidden,
            )
        )
    for c in parsed.cells:
        session.add(
            DocCell(
                document_id=doc.id,
                page=c.page,
                tbl=c.table,
                item=c.item,
                line=c.line,
                col=c.col,
                header=c.header,
                text=c.text,
                bbox=c.bbox.model_dump(),
            )
        )
    doc.page_count = len(parsed.pages)
    doc.language = detect_language(parsed.full_text())
    render_pages(path, storage_path(f"renders/{doc.id}"))
    return S.PARSED


async def load_parsed(
    session: AsyncSession, doc: Document
) -> tuple[ParsedDocument, list[DocBlock], list[tuple[TableCell, DocCell]]]:
    blocks = (
        await session.scalars(
            select(DocBlock).where(DocBlock.document_id == doc.id).order_by(DocBlock.seq)
        )
    ).all()
    cells = (
        await session.scalars(
            select(DocCell).where(DocCell.document_id == doc.id).order_by(DocCell.id)
        )
    ).all()
    pairs = [
        (
            TableCell(
                page=c.page,
                table=c.tbl,
                item=c.item,
                line=c.line,
                col=c.col,
                header=c.header,
                text=c.text,
                bbox=FracBox(**c.bbox),
            ),
            c,
        )
        for c in cells
    ]
    parsed = ParsedDocument(
        sha256=doc.sha256,
        mime_type=doc.mime_type,
        pages=[PageInfo(page=p, width=1, height=1) for p in range(1, (doc.page_count or 1) + 1)],
        blocks=[
            Block(
                page=r.page,
                seq=r.seq,
                kind=r.kind,
                text=r.text,
                bbox=FracBox(**r.bbox),
                ocr=r.ocr,
                hidden=r.hidden,
            )
            for r in blocks
        ],
        cells=[tc for tc, _ in pairs],
    )
    return parsed, list(blocks), pairs


@register(S.PARSED, PipelineStep.REDACT, kind=INVOICE)
async def redact(session: AsyncSession, invoice: Invoice, ctx: dict[str, Any]) -> S:
    doc = await _document(session, invoice)
    parsed, blocks, pairs = await load_parsed(session, doc)
    red = redact_invoice(parsed)
    for b in blocks:
        b.text_redacted = red.blocks[b.seq]
    for tc, row in pairs:
        row.text_redacted = red.cells[id(tc)]
    await Vault(ctx["settings"].pii_vault_key.get_secret_value()).store(
        session, invoice.id, red.redactor.mapping()
    )
    first_page = " ".join(red.blocks[b.seq] for b in parsed.blocks if b.page == 1)
    doc.doc_type = invoice_kind(first_page).value
    doc.doc_type_method = "rule"
    doc.doc_type_confidence = 0.95
    return S.REDACTED


@register(S.REDACTED, PipelineStep.EXTRACT, kind=INVOICE)
async def extract(session: AsyncSession, invoice: Invoice, ctx: dict[str, Any]) -> S:
    gateway: LLMGateway = ctx["gateway"]
    doc = await _document(session, invoice)
    parsed, blocks, pairs = await load_parsed(session, doc)
    if any(b.text_redacted is None and b.text.strip() for b in blocks) or any(
        row.text_redacted is None for _, row in pairs
    ):
        # Never fall back to the original text: it would reach the model unredacted.
        raise RuntimeError(f"document {doc.id} has text without its redacted form")
    ex = await extract_invoice(
        parsed,
        {b.seq: b.text_redacted or "" for b in blocks},
        gateway,
        redacted_cells={id(tc): row.text_redacted or "" for tc, row in pairs},
    )
    await session.execute(delete(ExtractedField).where(ExtractedField.case_id == invoice.id))
    rows = [(f.name, f) for f in ex.header]
    rows += [(f"lines[{lr.n}].{name}", f) for lr in ex.lines for name, f in lr.fields.items()]
    for name, f in rows:
        session.add(
            ExtractedField(
                case_id=invoice.id,
                document_id=doc.id,
                field=name,
                value_raw=f.value_raw,
                value_norm=f.value_norm,
                source_quote=f.quote,
                page=f.page,
                bbox=f.bbox.model_dump() if f.bbox else None,
                grounded=f.grounded,
                confidence=f.confidence,
                checks=f.checks,
                method=ExtractionMethod.LLM_TEXT.value,
                model=",".join(ex.models)[:64],
                prompt_version=",".join(t.split("@", 1)[-1] for t in ex.prompt_tags)[:64],
            )
        )
    return S.EXTRACTED


def _values(rows: list[ExtractedField]) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Stored fields back into header values and per-line values, in item order."""
    header: dict[str, str] = {}
    lines: dict[int, dict[str, str]] = {}
    for r in rows:
        if r.value_raw is None:
            continue
        m = re.fullmatch(r"lines\[(\d+)\]\.(.+)", r.field)
        if m:
            lines.setdefault(int(m[1]), {})[m[2]] = r.value_raw
        else:
            header[r.field] = r.value_raw
    return header, [lines[n] for n in sorted(lines)]


@register(S.EXTRACTED, PipelineStep.VALIDATE, kind=INVOICE)
async def validate_step(session: AsyncSession, invoice: Invoice, ctx: dict[str, Any]) -> S:
    doc = await _document(session, invoice)
    rows = list(
        (
            await session.scalars(
                select(ExtractedField).where(ExtractedField.case_id == invoice.id)
            )
        ).all()
    )
    header, lines = _values(rows)
    result = validate(
        header,
        lines,
        ours(),
        pages_present=doc.page_count or 1,
        kind=doc.doc_type or "invoice",
        tolerance=tolerance(),
    )
    by_name = {r.field: r for r in rows}
    line_numbers = sorted({int(m[1]) for r in rows if (m := re.match(r"lines\[(\d+)\]", r.field))})
    for c in result.checks:
        for ref in c.fields:
            # validate() counts lines from 1 in reading order; stored names carry item numbers
            m = re.match(r"lines\[(\d+)\]\.(.+)", ref)
            if m and int(m[1]) <= len(line_numbers):
                ref = f"lines[{line_numbers[int(m[1]) - 1]}].{m[2]}"
            if (row := by_name.get(ref)) is not None:
                row.checks = {**(row.checks or {}), c.name: c.ok}
                row.confidence = _confidence(row)
    supplier_ico = re.sub(r"\D", "", header.get("supplier_ico", "")) or None
    number = header.get("invoice_number")
    duplicate = await _duplicate_of(session, invoice, supplier_ico, number)
    checks = [
        {"name": c.name, "ok": c.ok, "fields": c.fields, "detail": c.detail} for c in result.checks
    ]
    if duplicate is not None:
        checks.append(
            {"name": "duplicate", "ok": False, "fields": ["invoice_number"], "detail": duplicate}
        )
    invoice.doc_kind = doc.doc_type
    invoice.invoice_number = number
    invoice.supplier_ico = supplier_ico
    invoice.supplier_vat_id = (header.get("supplier_vat_id") or "").replace(" ", "") or None
    invoice.total = parse_number(header.get("total"))
    invoice.currency = (header.get("currency") or "")[:3] or None
    invoice.validation = checks
    return S.NEEDS_INFO if result.needs_info else S.VALIDATED


def _confidence(row: ExtractedField) -> float:
    """The rule-based score of extraction, now with the validation checks in."""
    from claimpilot_worker.extraction.extract import Field, score_confidence

    f = Field(row.field, row.value_raw, row.source_quote, row.page)
    f.grounded, f.checks = row.grounded, dict(row.checks or {})
    return score_confidence(f)


async def _duplicate_of(
    session: AsyncSession, invoice: Invoice, supplier_ico: str | None, number: str | None
) -> str | None:
    """The reference of an earlier invoice with the same supplier and number, if any."""
    if not supplier_ico or not number:
        return None
    other = (
        await session.scalars(
            select(Invoice).where(
                Invoice.supplier_ico == supplier_ico,
                Invoice.invoice_number == number,
                Invoice.id != invoice.id,
                Invoice.status != S.FAILED.value,
            )
        )
    ).first()
    return other.reference if other else None


class PrefetchedErp:
    """The ERP records one invoice needs, fetched before matching (matching itself is sync)."""

    def __init__(
        self, supplier: dict | None, order: dict | None, receipts: list[dict], known: bool
    ):
        self._supplier, self._order, self._receipts, self._known = supplier, order, receipts, known

    def supplier(self, ico: str | None, vat_id: str | None) -> dict | None:
        return self._supplier

    def order(self, number: str) -> dict | None:
        return self._order if self._order and self._order["number"] == number else None

    def receipts_for(self, number: str) -> list[dict]:
        return self._receipts

    def invoice_known(self, supplier_ico: str, number: str) -> bool:
        return self._known


async def _get(client: httpx.AsyncClient, url: str, **params: str) -> Any:
    resp = await client.get(url, params={k: v for k, v in params.items() if v})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()  # a server error is retried by the pipeline
    return resp.json()


async def prefetch(
    client: httpx.AsyncClient,
    session: AsyncSession,
    header: dict[str, str],
    kind: str,
) -> PrefetchedErp:
    ico = re.sub(r"\D", "", header.get("supplier_ico") or "")
    vat_id = (header.get("supplier_vat_id") or "").replace(" ", "").upper()
    supplier = await _get(client, "/suppliers", ico=ico, vat_id=vat_id)
    number = header.get("order_number")
    order = await _get(client, f"/orders/{number}") if supplier and number else None
    receipts = (await _get(client, f"/orders/{number}/receipts") or []) if order else []
    known = False
    original = header.get("original_invoice_number")
    if kind == "credit_note" and supplier and original:
        known = (
            await session.scalars(
                select(Invoice.id).where(
                    Invoice.supplier_ico == supplier["ico"],
                    Invoice.invoice_number == original,
                    Invoice.doc_kind == "invoice",
                )
            )
        ).first() is not None
    return PrefetchedErp(supplier, order, receipts, known)


@register(S.VALIDATED, PipelineStep.MATCH, kind=INVOICE)
async def match_step(session: AsyncSession, invoice: Invoice, ctx: dict[str, Any]) -> S:
    rows = list(
        (
            await session.scalars(
                select(ExtractedField).where(ExtractedField.case_id == invoice.id)
            )
        ).all()
    )
    header, lines = _values(rows)
    kind = invoice.doc_kind or "invoice"
    client = ctx.get("erp_client")
    if client is None:
        async with httpx.AsyncClient(base_url=ctx["settings"].erp_url, timeout=20) as own:
            erp = await prefetch(own, session, header, kind)
    else:
        erp = await prefetch(client, session, header, kind)
    result = match(header, lines, erp, match_settings(), kind=kind)
    line_numbers = sorted({int(m[1]) for r in rows if (m := re.match(r"lines\[(\d+)\]", r.field))})
    by_name = {r.field: r for r in rows}
    for f in result.findings:
        if f.line is None or f.line >= len(line_numbers):
            continue
        target = {
            "price_diff": "line_net",
            "short_delivery": "quantity",
            "over_delivery": "quantity",
        }
        if row := by_name.get(f"lines[{line_numbers[f.line]}].{target.get(f.kind, 'name')}"):
            row.checks = {**(row.checks or {}), f.kind: False}
            row.confidence = _confidence(row)
    invoice.matching = {
        "supplier": result.supplier["ico"] if result.supplier else None,
        "order": result.order["number"] if result.order else None,
        "findings": [{"kind": f.kind, "line": f.line, "detail": f.detail} for f in result.findings],
        "lines": [{"line": m.line, "order_line": m.order_line} for m in result.lines],
    }
    return S.NEEDS_INFO if result.needs_info else S.MATCHED


@register(S.MATCHED, PipelineStep.ROUTE, kind=INVOICE)
async def route_step(session: AsyncSession, invoice: Invoice, ctx: dict[str, Any]) -> S:
    doc = await _document(session, invoice)
    parsed, blocks, _ = await load_parsed(session, doc)
    signals = document_signals(parsed, {b.seq: b.text_redacted or "" for b in blocks})
    route = route_invoice(
        invoice.validation or [],
        (invoice.matching or {}).get("findings", []),
        kind=invoice.doc_kind or "invoice",
        total=invoice.total,
        senior_amount=Decimal(config()["routing"]["senior_amount"]),
        injection=[f"page {s.page}: {s.kind}" for s in signals],
    )
    invoice.queue = route.queue.value
    invoice.routing = [{"rule": h.rule, "detail": h.detail} for h in route.hits]
    return S.ROUTED


@register(S.ROUTED, PipelineStep.SUMMARIZE, kind=INVOICE)
async def ready_for_review(session: AsyncSession, invoice: Invoice, ctx: dict[str, Any]) -> S:
    """Nothing to write for an invoice yet: the review screen shows the checks themselves."""
    return S.IN_REVIEW


@register(S.APPROVED, PipelineStep.SUBMIT, kind=INVOICE)
async def export_step(session: AsyncSession, invoice: Invoice, ctx: dict[str, Any]) -> S:
    """APPROVED -> EXPORTED: the approved values as Peppol UBL to the ERP. A refusal sends the
    invoice back to review with the rules it broke (ADR-015)."""
    rows = list(
        (
            await session.scalars(
                select(ExtractedField).where(ExtractedField.case_id == invoice.id)
            )
        ).all()
    )
    header, lines = _values(rows)
    client = ctx.get("erp_client")
    own = None
    if client is None:
        own = client = httpx.AsyncClient(base_url=ctx["settings"].erp_url, timeout=30)
    try:
        ico = re.sub(r"\D", "", header.get("supplier_ico") or "")
        vat_id = (header.get("supplier_vat_id") or "").replace(" ", "").upper()
        supplier = await _get(client, "/suppliers", ico=ico, vat_id=vat_id)
        buyer_ico = re.sub(r"\D", "", header.get("buyer_ico") or "")
        buyer = next((b for b in config()["buyers"] if b["ico"] == buyer_ico), None)
        try:
            body = build_ubl(
                from_values(
                    header,
                    lines,
                    kind=invoice.doc_kind or "invoice",
                    supplier_record=supplier,
                    buyer_record=buyer,
                )
            )
        except ExportError as exc:
            invoice.export = {"errors": [{"rule": "READ", "field": exc.field, "message": str(exc)}]}
            return S.IN_REVIEW
        path = storage_path(f"invoices/{invoice.id}/export.xml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        resp = await client.post(
            "/invoices", content=body, headers={"content-type": "application/xml"}
        )
    finally:
        if own is not None:
            await own.aclose()
    if resp.status_code == 422:
        invoice.export = {"errors": resp.json()["detail"]["errors"]}
        return S.IN_REVIEW
    if resp.status_code == 409:
        invoice.export = {"note": "posted before; the ERP keeps the first one"}
        return S.EXPORTED
    resp.raise_for_status()  # a server error is retried by the pipeline
    invoice.erp_id = resp.json()["erp_id"]
    invoice.export = {"erp_id": invoice.erp_id, "errors": []}
    return S.EXPORTED
