"""Reference payout calculation for ground truth.

Deliberately written apart from the payout engine in the worker (ADR-006): a short, literal reading
of products.yaml and the VPP, so one bug cannot hide in both the engine and its ground truth.
"""

from decimal import Decimal

from claimpilot_core.domain import ClaimStatus, Coverage, CoverageVerdict
from claimpilot_core.fx import FxSnapshot
from claimpilot_core.policy import ProductCatalog
from claimpilot_datagen.model import Scenario

ZERO = Decimal(0)


def apply_reference_payout(s: Scenario, catalog: ProductCatalog, fx: FxSnapshot) -> None:
    if s.expected_status is ClaimStatus.NEEDS_INFO:
        s.expected_total_payout_eur = None
        return
    product = catalog.product(s.product)
    covered = [i for i in s.items if i.verdict is CoverageVerdict.COVERED]
    by_cov: dict[str, Decimal] = {}
    deductibles = ZERO

    def remaining(cov: Coverage, limit: Decimal) -> Decimal:
        return max(limit - s.policy.prior_paid.get(cov, ZERO), ZERO)

    # Medical (A4.1-A4.4): one deductible per event, dental capped by its sublimit, then the limit.
    med = [i for i in covered if i.coverage is Coverage.MEDICAL]
    terms = product.coverage(Coverage.MEDICAL)
    if med and terms:
        dental = sum((fx.to_eur(i.amount, i.currency) for i in med if i.category == "dental"), ZERO)
        other = sum((fx.to_eur(i.amount, i.currency) for i in med if i.category != "dental"), ZERO)
        base = other + min(dental, terms.sublimits.get("dental", dental))
        ded = min(terms.deductible, base)
        pay = min(base - ded, remaining(Coverage.MEDICAL, terms.limit or ZERO))
        deductibles += ded
        by_cov[Coverage.MEDICAL] = pay

    # Accident (A6.1-A6.2): fixed fracture benefit, once per event.
    acc = [i for i in covered if i.coverage is Coverage.ACCIDENT]
    terms = product.coverage(Coverage.ACCIDENT)
    if acc and terms and terms.fracture_benefit:
        by_cov[Coverage.ACCIDENT] = terms.fracture_benefit

    # Luggage (A7.2-A7.3): per-item cap, valuables share of the limit, one deductible, then limit.
    lug = [i for i in covered if i.coverage is Coverage.LUGGAGE]
    terms = product.coverage(Coverage.LUGGAGE)
    if lug and terms and terms.limit:
        per_item = terms.per_item_limit or terms.limit
        capped = [(min(fx.to_eur(i.amount, i.currency), per_item), i.valuables) for i in lug]
        valuables = sum((a for a, v in capped if v), ZERO)
        valuables_cap = (terms.limit * (terms.valuables_share or Decimal(1))).quantize(
            Decimal("0.01")
        )
        base = sum((a for a, v in capped if not v), ZERO) + min(valuables, valuables_cap)
        ded = min(terms.deductible, base)
        pay = min(base - ded, remaining(Coverage.LUGGAGE, terms.limit))
        deductibles += ded
        by_cov[Coverage.LUGGAGE] = pay

    # Delay (A8.1-A8.3): receipts up to the limit when the delay is over the minimum hours.
    dly = [i for i in covered if i.coverage is Coverage.DELAY]
    terms = product.coverage(Coverage.DELAY)
    if dly and terms and terms.limit:
        hours = s.facts.get("delay_hours", 0)
        if hours > (terms.min_hours or 0):
            spent = sum((fx.to_eur(i.amount, i.currency) for i in dly), ZERO)
            by_cov[Coverage.DELAY] = min(spent, terms.limit)

    # Cancellation (A9.2): 80 % of the fee up to the limit.
    can = [i for i in covered if i.coverage is Coverage.CANCELLATION]
    terms = product.coverage(Coverage.CANCELLATION)
    if can and terms and terms.limit:
        fee = sum((fx.to_eur(i.amount, i.currency) for i in can), ZERO)
        rate = terms.reimbursement_rate or Decimal(1)
        by_cov[Coverage.CANCELLATION] = min((fee * rate).quantize(Decimal("0.01")), terms.limit)

    s.expected_by_coverage = {str(k): v for k, v in by_cov.items()}
    s.expected_total_payout_eur = sum(by_cov.values(), ZERO)
    s.expected_deductible_eur = deductibles
