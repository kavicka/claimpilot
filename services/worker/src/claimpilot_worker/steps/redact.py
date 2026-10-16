"""PARSED -> REDACTED: PII guard over the claim, vault, then document typing on redacted text."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import Claim, DocBlock, Document
from claimpilot_core.domain import ClaimStatus as S
from claimpilot_core.domain import PipelineStep
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.pii.guard import ClaimRedactor
from claimpilot_core.pii.vault import Vault
from claimpilot_worker.ingest.doctype import classify
from claimpilot_worker.pipeline import register


@register(S.PARSED, PipelineStep.REDACT)
async def redact(session: AsyncSession, claim: Claim, ctx: dict[str, Any]) -> S:
    docs = (await session.scalars(select(Document).where(Document.claim_id == claim.id))).all()
    blocks = {
        d.id: (
            await session.scalars(
                select(DocBlock).where(DocBlock.document_id == d.id).order_by(DocBlock.seq)
            )
        ).all()
        for d in docs
    }
    redactor = ClaimRedactor()
    redactor.observe(b.text for bs in blocks.values() for b in bs)
    for bs in blocks.values():
        for b in bs:
            b.text_redacted = redactor.redact(b.text)
    await Vault(ctx["settings"].pii_vault_key.get_secret_value()).store(
        session, claim.id, redactor.mapping()
    )
    gateway: LLMGateway = ctx["gateway"]
    for d in docs:
        visible = "\n".join(b.text_redacted or "" for b in blocks[d.id] if not b.hidden)
        result = await classify(visible, gateway)
        d.doc_type, d.doc_type_confidence, d.doc_type_method = (
            result.doc_type.value,
            result.confidence,
            result.method,
        )
    return S.REDACTED
