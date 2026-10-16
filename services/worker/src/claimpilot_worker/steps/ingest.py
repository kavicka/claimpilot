"""RECEIVED -> PARSED: parse every document into doc_blocks, cache page renders, flag duplicates."""

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import Claim, DocBlock, Document, Summary
from claimpilot_core.domain import ClaimStatus as S
from claimpilot_core.domain import PipelineStep
from claimpilot_worker.ingest.check import Problem, problem_of, unreadable_request
from claimpilot_worker.ingest.language import detect_language
from claimpilot_worker.ingest.parser import parse
from claimpilot_worker.ingest.renders import render_pages
from claimpilot_worker.pipeline import register
from claimpilot_worker.steps.common import storage_path

MIN_OCR_CHARS = 80  # below this a page is treated as unreadable and goes to the vision model


@register(S.RECEIVED, PipelineStep.INGEST)
async def ingest(session: AsyncSession, claim: Claim, ctx: dict[str, Any]) -> S:
    docs = (await session.scalars(select(Document).where(Document.claim_id == claim.id))).all()
    problems: dict[str, Problem] = {}
    for doc in docs:
        path = storage_path(doc.storage_path)
        problem = problem_of(path)
        doc.problem = problem.detail if problem else None
        if problem:
            problems[doc.filename] = problem
            continue
        parsed = parse(path)
        await session.execute(delete(DocBlock).where(DocBlock.document_id == doc.id))
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
        doc.page_count = len(parsed.pages)
        doc.language = detect_language(parsed.full_text())
        doc.needs_vision = not parsed.has_text_layer and len(parsed.full_text()) < MIN_OCR_CHARS
        render_pages(path, storage_path(f"renders/{doc.id}"))
    await session.execute(
        delete(Summary).where(Summary.claim_id == claim.id, Summary.kind == "info_request")
    )
    if problems:
        session.add(
            Summary(
                claim_id=claim.id,
                kind="info_request",
                language="sk",
                text=unreadable_request(problems),
            )
        )
        return S.NEEDS_INFO
    return S.PARSED
