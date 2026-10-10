"""EXTRACTED -> ROUTED | NEEDS_INFO: routing rules, the model only for R9 claims."""

from typing import Any

from sqlalchemy import delete

from claimpilot_core.db.models import Claim, RoutingDecision, Summary
from claimpilot_core.domain import ClaimStatus as S
from claimpilot_core.domain import DocType, PipelineStep
from claimpilot_core.fx import default_fx
from claimpilot_worker.context import first, history_for, load_docs, to_date
from claimpilot_worker.pipeline import register
from claimpilot_worker.routing.facts import build_facts
from claimpilot_worker.routing.route import route
from claimpilot_worker.submission.core_client import CoreClient


def info_request(missing: str) -> str:
    return (
        "Vážená pani / Vážený pán,\n\n"
        "na posúdenie Vašej poistnej udalosti potrebujeme doplniť tieto doklady: "
        f"{missing}. Kým ich nedostaneme, lehota na vybavenie neplynie (čl. 13 ods. 3 VPP).\n\n"
        "Doklady nahrajte prosím na portáli alebo ich pošlite e-mailom "
        "s číslom poistnej udalosti.\n\n"
        "S pozdravom\nOddelenie likvidácie poistných udalostí\nVzorová poisťovňa, a. s."
    )


# What later steps need from the policy record. Insured names and birth numbers stay in the core
# system: claims.facts is plain JSON that the review api and the MCP server read.
POLICY_TERMS = ("policy_number", "product", "kind", "start", "end", "issue_date", "prior_paid")


def policy_terms(policy: dict[str, Any] | None) -> dict[str, Any] | None:
    return {k: policy.get(k) for k in POLICY_TERMS} if policy else None


@register(S.EXTRACTED, PipelineStep.ROUTE)
async def route_claim(session, claim: Claim, ctx: dict[str, Any]) -> S:
    stored = await load_docs(session, claim.id)
    docs = [s.doc for s in stored]
    form = first(docs, DocType.CLAIM_FORM)
    policy = None
    if form and form.value("policy_number"):
        core = CoreClient(ctx["settings"].core_mock_url)
        try:
            policy = await core.policy(form.value("policy_number") or "")
        finally:
            await core.aclose()
    history = await history_for(session, claim.id)
    facts = build_facts(
        docs,
        default_fx(ctx["settings"].config_dir),
        history,
        claim_id=str(claim.id),
        policy_issue_date=to_date(policy["issue_date"]) if policy else None,
    )
    decision = await route(facts, docs, ctx["gateway"])
    r = decision.result
    claim.claim_type = facts.claim_type.value if facts.claim_type else None
    claim.queue = r.queue.value if r.queue else None
    claim.facts = {
        "claim_type": claim.claim_type,
        "claimed_total_eur": str(facts.claimed_total_eur)
        if facts.claimed_total_eur is not None
        else None,
        "event_date": facts.event_date.isoformat() if facts.event_date else None,
        "policy": policy_terms(policy),
        "min_critical_confidence": facts.min_critical_confidence,
        "critical_grounded": facts.critical_grounded,
    }
    session.add(
        RoutingDecision(
            claim_id=claim.id,
            queue=claim.queue or "needs_info",
            rule_hits=r.hits_json(),
            llm_used=decision.llm_used,
            rationale=decision.rationale,
        )
    )
    if r.status is S.NEEDS_INFO:
        missing = next(h.detail for h in r.hits if h.rule == "R4").removeprefix("missing: ")
        await session.execute(  # a reassessment must not leave two requests to the client
            delete(Summary).where(Summary.claim_id == claim.id, Summary.kind == "info_request")
        )
        session.add(
            Summary(
                claim_id=claim.id, kind="info_request", language="sk", text=info_request(missing)
            )
        )
        return S.NEEDS_INFO
    return S.ROUTED
