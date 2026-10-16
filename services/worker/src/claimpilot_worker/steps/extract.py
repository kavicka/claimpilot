"""REDACTED -> EXTRACTED: grounded extraction per document, then cross-document checks."""

from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import Claim, DocBlock, Document, ExtractedField
from claimpilot_core.domain import ClaimStatus as S
from claimpilot_core.domain import DocType, PipelineStep
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.pii.guard import ClaimRedactor
from claimpilot_core.pii.vault import Vault
from claimpilot_core.schemas.parsing import Block, FracBox, PageInfo, ParsedDocument
from claimpilot_worker.extraction.crossdoc import cross_document_checks
from claimpilot_worker.extraction.extract import (
    Extraction,
    extract_document,
    extract_document_vision,
)
from claimpilot_worker.ingest.mask import has_personal_data, mask_pages
from claimpilot_worker.ingest.renders import page_png_b64
from claimpilot_worker.pipeline import register

log = structlog.get_logger(__name__)


def _parsed(doc: Document, rows: list[DocBlock]) -> tuple[ParsedDocument, dict[int, str]]:
    blocks = [
        Block(
            page=r.page,
            seq=r.seq,
            kind=r.kind,
            text=r.text,
            bbox=FracBox(**r.bbox),
            ocr=r.ocr,
            hidden=r.hidden,
        )
        for r in rows
    ]
    pages = [PageInfo(page=p, width=1, height=1) for p in sorted({r.page for r in rows})]
    parsed = ParsedDocument(sha256=doc.sha256, mime_type=doc.mime_type, pages=pages, blocks=blocks)
    if any(r.text_redacted is None and r.text.strip() for r in rows):
        # Never fall back to the original text: it would reach the model unredacted.
        raise RuntimeError(f"document {doc.id} has blocks without redacted text")
    return parsed, {r.seq: r.text_redacted or "" for r in rows}


@register(S.REDACTED, PipelineStep.EXTRACT)
async def extract(session: AsyncSession, claim: Claim, ctx: dict[str, Any]) -> S:
    gateway: LLMGateway = ctx["gateway"]
    settings = ctx["settings"]
    vault = Vault(settings.pii_vault_key.get_secret_value())
    entries = await vault.load_entries(session, claim.id)
    mapping = {t: v for t, (_, v) in entries.items()}
    vision = settings.scan_path == "vision"
    # Page images hold personal data: unmasked they go to local models only (ADR-003); a cloud
    # model gets them masked, or not at all (ADR-010).
    local_vision = gateway.spec_for("extraction_vision").provider == "ollama"
    redactor: ClaimRedactor | None = None

    def tokenize(value: str) -> str:
        assert redactor is not None
        out = redactor.tokenize(value)
        mapping.update({t: v for t, (_, v) in redactor.mapping().items()})
        return out

    docs = (await session.scalars(select(Document).where(Document.case_id == claim.id))).all()
    extractions: dict[Any, Extraction] = {}
    for doc in docs:
        rows = (
            await session.scalars(
                select(DocBlock).where(DocBlock.document_id == doc.id).order_by(DocBlock.seq)
            )
        ).all()
        parsed, redacted = _parsed(doc, list(rows))
        images: list[str] | None = None
        if vision and any(r.ocr for r in rows):
            redactor = redactor or ClaimRedactor.from_mapping(entries)
            path = settings.storage_dir / doc.storage_path
            images = [page_png_b64(path, p.page) for p in parsed.pages]
            if not local_vision:
                images, report = mask_pages(images, parsed, has_personal_data(redactor))
                if images is None:
                    log.info("vision.masking_refused", document=str(doc.id), reason=report.refused)
        if images is not None:
            assert redactor is not None
            ex = await extract_document_vision(
                DocType(doc.doc_type),
                images,
                parsed,
                redacted,
                gateway,
                tokenize=tokenize,
                mapping=mapping,
                masked=not local_vision,
            )
        else:
            ex = await extract_document(
                DocType(doc.doc_type),
                parsed,
                redacted,
                gateway,
                language=doc.language or "en",
                mapping=mapping,
            )
        extractions[doc.id] = ex
    if redactor is not None and len(redactor.entities) > len(entries):
        await vault.store(session, claim.id, redactor.mapping())  # values only the image showed
    cross_document_checks(list(extractions.values()))
    await session.execute(delete(ExtractedField).where(ExtractedField.case_id == claim.id))
    for doc_id, ex in extractions.items():
        for f in ex.fields:
            session.add(
                ExtractedField(
                    case_id=claim.id,
                    document_id=doc_id,
                    field=f.name,
                    value_raw=f.value_raw,
                    value_norm=f.value_norm,
                    source_quote=f.quote,
                    page=f.page,
                    bbox=f.bbox.model_dump() if f.bbox else None,
                    grounded=f.grounded,
                    confidence=f.confidence,
                    checks=f.checks,
                    method=ex.method.value,
                    model=ex.model,
                    prompt_version=ex.prompt_tag,
                )
            )
    return S.EXTRACTED
