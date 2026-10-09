"""Payout engine: limits, sublimits, deductibles, FX and prior payouts, in plain Python (ADR-002).

Per coverage section: convert each covered item to EUR with the contract's FX snapshot (A12.1),
apply per-item caps and sublimits, subtract one deductible per event, cap by what is left of the
limit after earlier payouts. The result is split back onto items so the review UI can show a line
per invoice or lost object, and every step is written to `explanation` with its clause.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from claimpilot_core.domain import Coverage, CoverageVerdict
from claimpilot_core.fx import FxSnapshot
from claimpilot_core.policy import ProductTerms

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class PayoutItem:
    ref: str
    coverage: Coverage
    category: str
    amount: Decimal
    currency: str
    verdict: CoverageVerdict
    valuables: bool = False
    amount_eur: Decimal = ZERO
    base: Decimal = ZERO  # after per-item caps and sublimits
    payout: Decimal = ZERO


@dataclass
class PayoutResult:
    items: list[PayoutItem]
    by_coverage: dict[Coverage, Decimal] = field(default_factory=dict)
    deductible: Decimal = ZERO
    held: Decimal = ZERO  # needs_review items: claimed, not paid until a handler decides
    explanation: list[str] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return money(sum(self.by_coverage.values(), ZERO))


def _distribute(items: list[PayoutItem], total: Decimal) -> None:
    """Set item payouts so they sum to `total`: bases in order, the last item absorbs rounding."""
    left = total
    for it in items:
        it.payout = min(it.base, left)
        left -= it.payout
    if items and left > 0:
        items[-1].payout += left


def compute_payout(
    terms: ProductTerms,
    items: list[PayoutItem],
    fx: FxSnapshot,
    *,
    prior_paid: dict[Coverage, Decimal] | None = None,
    delay_hours: int | None = None,
) -> PayoutResult:
    prior_paid = prior_paid or {}
    result = PayoutResult(items=items)
    for it in items:
        it.amount_eur = fx.to_eur(it.amount, it.currency)
        it.base = it.payout = ZERO
        if it.verdict is CoverageVerdict.NEEDS_REVIEW:
            result.held += it.amount_eur
    covered = [it for it in items if it.verdict is CoverageVerdict.COVERED]
    for cov in Coverage:
        group = [it for it in covered if it.coverage is cov]
        if not group:
            continue
        t = terms.coverage(cov)
        if t is None:
            result.explanation.append(f"{cov.value}: not included in {terms.name}")
            continue
        exp = result.explanation
        if cov is Coverage.ACCIDENT:
            benefit = money(t.fracture_benefit or ZERO)
            group[0].base = benefit
            _distribute(group, benefit)
            result.by_coverage[cov] = benefit
            exp.append(
                f"accident: fixed fracture benefit {benefit} EUR, once per event (A6.1, A6.2)"
            )
            continue
        for it in group:
            it.base = it.amount_eur
        if cov is Coverage.MEDICAL and "dental" in t.sublimits:
            dental = [it for it in group if it.category == "dental"]
            cap = t.sublimits["dental"]
            spent = ZERO
            for it in dental:
                it.base = max(min(it.base, cap - spent), ZERO)
                spent += it.base
            if sum((it.amount_eur for it in dental), ZERO) > cap:
                exp.append(f"medical: dental capped at the sublimit {money(cap)} EUR (A4.4)")
        if cov is Coverage.LUGGAGE:
            if t.per_item_limit is not None:
                for it in group:
                    if it.base > t.per_item_limit:
                        it.base = money(t.per_item_limit)
                        exp.append(
                            f"luggage: {it.ref} capped at {money(t.per_item_limit)} EUR "
                            "per item (A7.2)"
                        )
            if t.valuables_share is not None and t.limit is not None:
                cap = money(t.limit * t.valuables_share)
                spent = ZERO
                for it in [x for x in group if x.valuables]:
                    allowed = max(min(it.base, cap - spent), ZERO)
                    if allowed < it.base:
                        exp.append(
                            f"luggage: valuables capped at {cap} EUR, 30 % of the limit (A7.3)"
                        )
                    it.base = allowed
                    spent += allowed
        if cov is Coverage.DELAY and (delay_hours or 0) <= (t.min_hours or 0):
            exp.append(
                f"delay: {delay_hours} h is not more than {t.min_hours} h, nothing payable (A8.3)"
            )
            result.by_coverage[cov] = ZERO
            continue
        base = money(sum((it.base for it in group), ZERO))
        if cov is Coverage.CANCELLATION and t.reimbursement_rate is not None:
            rated = money(base * t.reimbursement_rate)
            exp.append(
                f"cancellation: {t.reimbursement_rate:.0%} of {base} EUR = {rated} EUR (A9.2)"
            )
            base = rated
        deductible = min(money(t.deductible), base)
        if deductible:
            exp.append(f"{cov.value}: deductible {deductible} EUR, once per event")
        result.deductible += deductible
        payable = base - deductible
        remaining = max(money((t.limit or payable) - prior_paid.get(cov, ZERO)), ZERO)
        if payable > remaining:
            exp.append(
                f"{cov.value}: capped at the remaining limit {remaining} EUR"
                f"{' after earlier payouts' if prior_paid.get(cov) else ''}"
            )
            payable = remaining
        payable = money(payable)
        if cov is Coverage.CANCELLATION and t.reimbursement_rate is not None:
            for it in group:
                it.base = money(it.base * t.reimbursement_rate)
        # The deductible and caps come off the items in order (see _distribute).
        _distribute(group, payable)
        result.by_coverage[cov] = payable
    result.deductible = money(result.deductible)
    result.held = money(result.held)
    return result
