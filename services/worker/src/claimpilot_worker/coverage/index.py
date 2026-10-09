"""Coverage index: VPP chunks with bge-m3 embeddings and an unaccented full-text vector."""

from pathlib import Path

from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.db.models import PolicyChunk
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_worker.coverage.chunker import Chunk, chunk_pdf


def chunk_text(c: Chunk) -> str:
    """What gets embedded and searched; the article heading gives short paragraphs a topic."""
    return f"Článok {c.article} {c.heading}, odsek {c.paragraph}: {c.text}"


async def build_index(session: AsyncSession, pdf: Path, gateway: LLMGateway) -> int:
    chunks = chunk_pdf(pdf)
    vectors = await gateway.embed([chunk_text(c) for c in chunks])
    await session.execute(delete(PolicyChunk))
    for c, vec in zip(chunks, vectors, strict=True):
        session.add(
            PolicyChunk(
                clause_id=c.clause_id,
                products=[],
                article=c.article,
                paragraph=c.paragraph,
                page=c.page,
                heading=c.heading,
                text=c.text,
                embedding=vec,
            )
        )
    await session.flush()
    await session.execute(
        text(
            "UPDATE policy_chunks "
            "SET tsv = to_tsvector('simple', f_unaccent(heading || ' ' || text))"
        )
    )
    return len(chunks)
