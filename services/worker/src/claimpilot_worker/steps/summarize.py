"""ASSESSED -> IN_REVIEW: handler summary, client letter and group summary, fact-checked."""

from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select

from claimpilot_core.db.models import Claim, CoverageDecision, RoutingDecision, Summary
from claimpilot_core.domain import ClaimStatus as S
from claimpilot_core.domain import DocType, PipelineStep
from claimpilot_core.policy import load_products
from claimpilot_core.settings import repo_root
from claimpilot_worker.context import first, load_docs, to_date
from claimpilot_worker.pipeline import register
from claimpilot_worker.summaries.write import DecisionFacts, write_all


@register(S.ASSESSED, PipelineStep.SUMMARIZE)
async def summarize(session, claim: Claim, ctx: dict[str, Any]) -> S:
    docs = [s.doc for s in await load_docs(session, claim.id)]
    form = first(docs, DocType.CLAIM_FORM)
    items = (
        await session.scalars(
            select(CoverageDecision)
            .where(CoverageDecision.claim_id == claim.id)
            .order_by(CoverageDecision.id)
        )
    ).all()
    routing = (
        await session.scalars(
            select(RoutingDecision)
            .where(RoutingDecision.claim_id == claim.id)
            .order_by(RoutingDecision.id.desc())
        )
    ).first()
    a = claim.assessment or {}
    product = (
        load_products(repo_root() / "data" / "policies" / "products.yaml")
        .product(claim.product)
        .name
        if claim.product
        else "neznámy produkt"
    )
    facts = DecisionFacts(
        reference=claim.reference,
        product=product,
        claim_type=claim.claim_type or "unknown",
        event_date=to_date(form.value("event_date")) if form else None,
        queue=claim.queue,
        items=[
            {
                "description": i.item_description,
                "amount": i.claimed_amount,
                "currency": i.claimed_currency,
                "verdict": i.verdict,
                "clauses": i.clause_ids,
                "payout": i.payout_eur,
            }
            for i in items
        ],
        total_payout=Decimal(a.get("total_payout_eur") or 0),
        deductible=Decimal(a.get("deductible_eur") or 0),
        red_flags=[
            f"{h['rule']}: {h['detail']}"
            for h in (routing.rule_hits if routing else [])
            if h["rule"] != "R8"
        ],
        missing=[],
        insured_token=(form.raw_value("insured_name") if form else None) or "<PERSON_1>",
    )
    await session.execute(
        delete(Summary).where(Summary.claim_id == claim.id, Summary.kind != "info_request")
    )
    for t in await write_all(facts, ctx["gateway"]):
        session.add(
            Summary(
                claim_id=claim.id,
                kind=t.kind,
                language=t.language,
                text=t.text,
                fact_violations=[v.__dict__ for v in t.violations],
                prompt_version=t.prompt_tag,
            )
        )
    return S.IN_REVIEW
