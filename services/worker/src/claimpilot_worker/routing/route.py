"""Routing step logic: rules first, the model only for claims the rules leave at R9."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from claimpilot_core.domain import DocType, Queue
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.llm.untrusted import wrap
from claimpilot_worker.routing.facts import DocInput
from claimpilot_worker.routing.rules import ClaimFacts, RoutingResult, RuleHit, evaluate


class Review(BaseModel):
    queue: Literal["standard", "senior", "fraud_review"]
    rationale: str = Field(description="One or two sentences citing what was seen")


@dataclass
class RoutingDecision:
    result: RoutingResult
    llm_used: bool
    rationale: str


async def route(
    facts: ClaimFacts, docs: list[DocInput], gateway: LLMGateway | None
) -> RoutingDecision:
    result = evaluate(facts)
    rationale = "; ".join(f"{h.rule}: {h.detail}" for h in result.hits) or "no rule hit"
    if not result.needs_llm or gateway is None:
        return RoutingDecision(result, False, rationale)
    form = next((d for d in docs if d.doc_type is DocType.CLAIM_FORM and d.extraction), None)
    description = (
        form.extraction.raw_value("event_description") if form and form.extraction else None
    ) or "(none)"
    reports = [d.redacted_text[:2500] for d in docs if d.doc_type is DocType.MEDICAL_REPORT] or [
        "(none)"
    ]
    gen = await gateway.generate_json(
        "routing",
        "routing/review",
        Review,
        {
            "claim_type": facts.claim_type.value if facts.claim_type else "unknown",
            "total": facts.claimed_total_eur if facts.claimed_total_eur is not None else "unknown",
            "documents": ", ".join(d.doc_type.value for d in docs),
            "description": wrap(description, "client's description"),
            "reports": "\n".join(wrap(r, "medical report") for r in reports),
        },
    )
    review = gen.value
    if review.queue != "standard":
        result.queue = Queue(review.queue)
        result.rule = "LLM"
        result.hits.append(RuleHit("LLM", review.rationale))
    return RoutingDecision(result, True, f"LLM: {review.rationale}")
