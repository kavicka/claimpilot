"""Hybrid retrieval over the VPP: vector and full-text top 20 each, reciprocal rank fusion,
cross-encoder rerank to the top 5. Postgres ships no Slovak text-search config, so full-text uses
the simple config over unaccented words."""

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_core.llm.gateway import LLMGateway

RRF_K = 60
CANDIDATES = 20


@dataclass
class Hit:
    clause_id: str
    heading: str
    text: str
    score: float
    sources: list[str]


@lru_cache(maxsize=1)
def _reranker():
    import torch
    from sentence_transformers import CrossEncoder

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    return CrossEncoder("BAAI/bge-reranker-v2-m3", device=device, max_length=512)


def _fts_query(query: str) -> str:
    """OR of the query's content words, so a long query still matches short paragraphs."""
    import re

    from claimpilot_core.pii.guard import fold

    words = [w for w in re.findall(r"[^\W\d_]{4,}", fold(query))][:24]
    return " | ".join(dict.fromkeys(words)) or "x"


def rrf(lists: dict[str, Sequence[Sequence[str]]]) -> list[Hit]:
    """Reciprocal rank fusion of ranked (clause_id, heading, text) lists; ties keep first-seen
    order."""
    fused: dict[str, Hit] = {}
    for source, rows in lists.items():
        for rank, (cid, heading, body) in enumerate(rows, start=1):
            hit = fused.setdefault(cid, Hit(cid, heading, body, 0.0, []))
            hit.score += 1.0 / (RRF_K + rank)
            hit.sources.append(source)
    return sorted(fused.values(), key=lambda h: h.score, reverse=True)


async def hybrid(
    session: AsyncSession, gateway: LLMGateway, query: str, *, k: int = 5, rerank: bool = True
) -> list[Hit]:
    (vec,) = await gateway.embed([query], kind="query")
    vector_rows = (
        await session.execute(
            text(
                "SELECT clause_id, heading, text FROM policy_chunks "
                "ORDER BY embedding <=> CAST(:v AS vector) LIMIT :n"
            ),
            {"v": str(vec), "n": CANDIDATES},
        )
    ).all()
    fts_rows = (
        await session.execute(
            text(
                "SELECT clause_id, heading, text FROM policy_chunks "
                "WHERE tsv @@ to_tsquery('simple', f_unaccent(:q)) "
                "ORDER BY ts_rank(tsv, to_tsquery('simple', f_unaccent(:q))) DESC LIMIT :n"
            ),
            {"q": _fts_query(query), "n": CANDIDATES},
        )
    ).all()
    ranked = rrf({"vector": vector_rows, "fts": fts_rows})[:CANDIDATES]
    if rerank and ranked:
        scores = _reranker().predict([(query, f"{h.heading}: {h.text}") for h in ranked])
        for h, s in zip(ranked, scores, strict=True):
            h.score = float(s)
        ranked.sort(key=lambda h: h.score, reverse=True)
    return ranked[:k]
