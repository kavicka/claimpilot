"""Coverage decision: items, deterministic pre-checks, Step A mapping, Step B verdicts, payout.

Pre-checks are code: an event outside the policy period (A3.2) or the trip (A3.3) and a document
already claimed elsewhere (A13.4) decide an item without a model. The model maps items to coverage
sections and judges textual exclusions, citing only clauses retrieval put in front of it.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field

from claimpilot_core.domain import ClaimType, Coverage, CoverageVerdict, DocType, Product
from claimpilot_core.fx import FxSnapshot
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.normalize import parse_amount, parse_currency
from claimpilot_core.policy import ProductCatalog, load_terms
from claimpilot_core.settings import repo_root
from claimpilot_worker.coverage.payout import PayoutItem, PayoutResult, compute_payout
from claimpilot_worker.coverage.retrieve import Hit
from claimpilot_worker.routing.facts import DocInput

CATEGORIES = Literal[
    "treatment",
    "hospital",
    "medication",
    "dental",
    "transport",
    "fracture",
    "luggage",
    "valuables",
    "essentials",
    "cancellation_fee",
    "liability",
]
Retriever = Callable[[str], Awaitable[list[Hit]]]


@dataclass
class ClaimItem:
    ref: str
    description: str
    amount: Decimal | None  # None: the amount or currency could not be read; a handler decides
    currency: str | None
    source: str | None = None
    coverage: Coverage | None = None
    category: str | None = None
    verdict: CoverageVerdict | None = None
    clause_ids: list[str] = field(default_factory=list)
    rationale: str = ""
    method: str = ""  # precheck | llm
    retrieved: list[str] = field(default_factory=list)


@dataclass
class CoverageOutcome:
    items: list[ClaimItem]
    payout: PayoutResult | None
    product: Product | None


class MappedItem(BaseModel):
    ref: str
    coverage: Literal["medical", "accident", "luggage", "delay", "cancellation", "liability"]
    category: CATEGORIES


class Mapping(BaseModel):
    items: list[MappedItem]


class Verdict(BaseModel):
    verdict: Literal["covered", "not_covered", "needs_review"]
    clause_ids: list[str] = Field(
        description="Ids of the clauses that decide it, from the list given"
    )
    rationale: str = Field(description="One or two sentences")


def items_from_claim(docs: list[DocInput]) -> list[ClaimItem]:
    """The claim form's rows are what the client claims; without a form, invoices and receipts."""
    form = next(
        (d.extraction for d in docs if d.doc_type is DocType.CLAIM_FORM and d.extraction), None
    )
    items: list[ClaimItem] = []
    if form:
        rows = sorted(
            {f.name.split("]")[0] for f in form.fields if f.name.startswith("claimed_items[")},
            key=lambda r: int(r.split("[")[1]),
        )
        for row in rows:
            desc = form.get(f"{row}].description")
            amount = parse_amount(form.value(f"{row}].amount"))
            currency = parse_currency(form.value(f"{row}].currency"))
            items.append(
                ClaimItem(
                    f"I{len(items) + 1}",
                    (desc.value_raw if desc else None) or "",
                    amount,
                    currency,
                    "claim_form",
                )
            )
    if items:
        return items
    for d in docs:
        if d.extraction and d.doc_type in (DocType.MEDICAL_INVOICE, DocType.PHARMACY_RECEIPT):
            amount = parse_amount(d.extraction.value("total"))
            currency = parse_currency(d.extraction.value("currency"))
            name = (
                d.extraction.value("provider_name")
                or d.extraction.value("pharmacy_name")
                or d.doc_type.value
            )
            items.append(ClaimItem(f"I{len(items) + 1}", name, amount, currency, d.doc_type.value))
    return items


def evidence(docs: list[DocInput]) -> str:
    parts = []
    for d in docs:
        if not d.extraction:
            continue
        for name in (
            "event_description",
            "anamnesis",
            "treatment",
            "diagnosis",
            "incident_description",
            "remarks",
            "status",
            "cancellation_date",
        ):
            f = d.extraction.get(name)
            if f and f.value_raw:
                parts.append(f"{d.doc_type.value}.{name}: {f.value_raw}")
        if (
            d.doc_type is DocType.POLICE_REPORT
            and (p := d.extraction.get("vehicle_plate"))
            and p.value_raw
        ):
            parts.append("police_report: a vehicle was involved")
    return "\n".join(parts)[:4000]


def precheck(
    item: ClaimItem,
    *,
    event: date | None,
    policy: tuple[date, date] | None,
    trip: tuple[date, date] | None,
    duplicate: bool,
    known_currencies: set[str] | None = None,
    issued: date | None = None,
) -> bool:
    cancellation = item.coverage is Coverage.CANCELLATION
    lump_sum = item.coverage is Coverage.ACCIDENT  # a fixed benefit: no amount to read
    if not lump_sum and (
        item.amount is None
        or item.currency is None
        or (known_currencies is not None and item.currency not in known_currencies)
    ):
        # Never assume EUR or zero: a misread currency changes the payout by a factor of 25.
        item.verdict, item.clause_ids = CoverageVerdict.NEEDS_REVIEW, []
        item.rationale = "the amount or its currency is missing or could not be read"
    elif duplicate and item.coverage is Coverage.MEDICAL:
        item.verdict, item.clause_ids = CoverageVerdict.NOT_COVERED, ["A13.4"]
        item.rationale = "the same invoice was already claimed in another claim"
    elif cancellation and event and issued and event < issued:
        item.verdict, item.clause_ids = CoverageVerdict.NOT_COVERED, ["A9.4"]
        item.rationale = f"the reason arose on {event}, before the policy was issued on {issued}"
    elif not cancellation and event and policy and not policy[0] <= event <= policy[1]:
        # A cancellation reason arises before the trip by definition; A3.3 says so for the trip
        # dates and the policy period of these synthetic contracts starts with the trip.
        item.verdict, item.clause_ids = CoverageVerdict.NOT_COVERED, ["A3.2"]
        item.rationale = f"event on {event} is outside the policy period {policy[0]} to {policy[1]}"
    elif event and trip and not cancellation and not trip[0] <= event <= trip[1]:
        item.verdict, item.clause_ids = CoverageVerdict.NOT_COVERED, ["A3.3"]
        item.rationale = f"event on {event} is outside the trip {trip[0]} to {trip[1]}"
    else:
        return False
    item.method = "precheck"
    return True


@lru_cache
def general_exclusions() -> tuple[Hit, ...]:
    """Article 11 applies to every item (alcohol, extreme sports, intent, war), so its clauses go to
    the model whether or not retrieval ranked them."""
    terms = load_terms(repo_root() / "data" / "policies" / "vpp_cp_2026.yaml")
    return tuple(
        Hit(c.clause_id, c.article_title, c.text, 0.0, ["always"])
        for c in terms.clauses
        if c.clause_id.startswith("A11.")
    )


def readable(item: ClaimItem, fx: FxSnapshot) -> tuple[Decimal, str]:
    """Amount and currency for the payout engine; an unreadable one counts as zero (the item is
    already marked needs_review, so nothing is paid on it)."""
    if item.amount is not None and item.currency and item.currency.upper() in fx.rates:
        return item.amount, item.currency
    return Decimal(0), "EUR"


async def decide_coverage(
    docs: list[DocInput],
    *,
    claim_type: ClaimType | None,
    product: Product | None,
    catalog: ProductCatalog,
    fx: FxSnapshot,
    gateway: LLMGateway,
    retrieve: Retriever,
    event: date | None,
    policy: tuple[date, date] | None,
    trip: tuple[date, date] | None,
    duplicate: bool,
    prior_paid: dict[Coverage, Decimal] | None = None,
    delay_hours: int | None = None,
    issued: date | None = None,
) -> CoverageOutcome:
    items = items_from_claim(docs)
    if not items:
        return CoverageOutcome([], None, product)
    ev = evidence(docs)
    mapping = await gateway.generate_json(
        "coverage_map",
        "coverage/map",
        Mapping,
        {
            "claim_type": claim_type.value if claim_type else "unknown",
            "documents": ", ".join(d.doc_type.value for d in docs),
            "items": [
                {"ref": i.ref, "description": i.description, "source": i.source} for i in items
            ],
            "evidence": ev[:1500] or "(none)",
        },
    )
    by_ref = {m.ref: m for m in mapping.value.items}
    for it in items:
        m = by_ref.get(it.ref)
        it.coverage = Coverage(m.coverage) if m else Coverage.MEDICAL
        it.category = m.category if m else "treatment"
    terms = catalog.product(product) if product else None
    for it in items:
        if precheck(
            it,
            event=event,
            policy=policy,
            trip=trip,
            duplicate=duplicate,
            known_currencies=set(fx.rates),
            issued=issued,
        ):
            continue
        section = it.coverage.value if it.coverage else ""
        query = f"{section} {it.category}: {it.description}\n{ev[:1200]}"
        hits = await retrieve(query)
        it.retrieved = [h.clause_id for h in hits]
        hits = hits + [h for h in general_exclusions() if h.clause_id not in it.retrieved]
        gen = await gateway.generate_json(
            "coverage_decide",
            "coverage/decide",
            Verdict,
            {
                "product": terms.name if terms else "unknown",
                "extreme_sports": bool(terms and terms.extreme_sports),
                "claim_type": claim_type.value if claim_type else "unknown",
                "item": it.description,
                "coverage": it.coverage.value if it.coverage else "?",
                "category": it.category,
                "evidence": ev or "(none)",
                "clauses": [
                    {"clause_id": h.clause_id, "heading": h.heading, "text": h.text} for h in hits
                ],
            },
        )
        v = gen.value
        allowed = {h.clause_id for h in hits}
        it.verdict = CoverageVerdict(v.verdict)
        it.clause_ids = [c for c in v.clause_ids if c in allowed]
        it.rationale = v.rationale
        it.method = "llm"
    payout = None
    if terms:
        payout = compute_payout(
            terms,
            [
                PayoutItem(
                    i.ref,
                    i.coverage or Coverage.MEDICAL,
                    i.category or "treatment",
                    *readable(i, fx),
                    i.verdict or CoverageVerdict.NEEDS_REVIEW,
                    i.category == "valuables",
                )
                for i in items
            ],
            fx,
            prior_paid=prior_paid,
            delay_hours=delay_hours,
        )
    return CoverageOutcome(items, payout, product)
