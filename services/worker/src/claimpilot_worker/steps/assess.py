"""ROUTED -> ASSESSED: coverage per item with cited clauses, payout computed in code."""

from typing import Any

from sqlalchemy import delete, select

from claimpilot_core.db.models import Claim, CoverageDecision, RoutingDecision
from claimpilot_core.domain import ClaimStatus as S
from claimpilot_core.domain import DocType, PipelineStep
from claimpilot_core.fx import default_fx
from claimpilot_core.policy import load_products
from claimpilot_core.settings import repo_root
from claimpilot_worker.context import (
    delay_hours,
    first,
    issued_on,
    load_docs,
    periods,
    prior_paid,
    product_of,
    to_date,
)
from claimpilot_worker.coverage.decide import decide_coverage
from claimpilot_worker.coverage.retrieve import hybrid
from claimpilot_worker.pipeline import register
from claimpilot_worker.routing.facts import claim_type_of


@register(S.ROUTED, PipelineStep.ASSESS)
async def assess(session, claim: Claim, ctx: dict[str, Any]) -> S:
    stored = await load_docs(session, claim.id)
    docs = [s.doc for s in stored]
    policy = (claim.facts or {}).get("policy")
    form = first(docs, DocType.CLAIM_FORM)
    routing = (
        await session.scalars(
            select(RoutingDecision)
            .where(RoutingDecision.claim_id == claim.id)
            .order_by(RoutingDecision.id.desc())
        )
    ).first()
    duplicate = bool(routing and any(h["rule"] == "R1" for h in routing.rule_hits))
    policy_period, trip = periods(docs, policy)

    async def retrieve(query: str):
        return await hybrid(session, ctx["gateway"], query, k=5)

    fx = default_fx(ctx["settings"].config_dir)
    outcome = await decide_coverage(
        docs,
        claim_type=claim_type_of(docs),
        product=product_of(docs, policy),
        catalog=load_products(repo_root() / "data" / "policies" / "products.yaml"),
        fx=fx,
        gateway=ctx["gateway"],
        retrieve=retrieve,
        event=to_date(form.value("event_date")) if form else None,
        policy=policy_period,
        trip=trip,
        duplicate=duplicate,
        prior_paid=prior_paid(policy),
        delay_hours=delay_hours(docs),
        issued=issued_on(docs, policy),
    )
    await session.execute(delete(CoverageDecision).where(CoverageDecision.claim_id == claim.id))
    payouts = {p.ref: p for p in outcome.payout.items} if outcome.payout else {}
    for it in outcome.items:
        p = payouts.get(it.ref)
        session.add(
            CoverageDecision(
                claim_id=claim.id,
                item_ref=it.ref,
                item_description=it.description,
                coverage=it.coverage.value if it.coverage else "",
                verdict=it.verdict.value if it.verdict else "needs_review",
                clause_ids=it.clause_ids,
                claimed_amount=it.amount,
                claimed_currency=it.currency,
                payout_eur=p.payout if p else 0,
                deductible_eur=0,
                rationale=f"[{it.method}] {it.rationale}",
                confidence=0.9 if it.method == "precheck" else 0.75,
            )
        )
    pay = outcome.payout
    claim.product = outcome.product.value if outcome.product else None
    claim.policy_id = form.value("policy_number") if form else None
    claim.assessment = {
        "total_payout_eur": str(pay.total) if pay else None,
        "deductible_eur": str(pay.deductible) if pay else None,
        "held_eur": str(pay.held) if pay else None,
        "by_coverage": {k.value: str(v) for k, v in pay.by_coverage.items()} if pay else {},
        "explanation": pay.explanation if pay else ["product unknown: payout not computed"],
    }
    return S.ASSESSED
