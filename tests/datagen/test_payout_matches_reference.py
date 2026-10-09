"""The payout engine and the generator's reference calculation are written apart (ADR-006).
On every synthetic claim they must agree to the cent."""

from pathlib import Path

import pytest

from claimpilot_core.domain import ClaimStatus
from claimpilot_core.fx import FxSnapshot
from claimpilot_core.policy import load_products
from claimpilot_datagen.reference import apply_reference_payout
from claimpilot_datagen.scenarios import Sampler
from claimpilot_worker.coverage.payout import PayoutItem, compute_payout

ROOT = Path(__file__).resolve().parents[2]
FX = FxSnapshot.load(ROOT / "config" / "fx_rates.yaml")
CATALOG = load_products(ROOT / "data" / "policies" / "products.yaml")
SCENARIOS = [s for s in Sampler(42, FX).build() if s.expected_status is not ClaimStatus.NEEDS_INFO]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: f"{s.scenario_id}-{s.archetype}")
def test_engine_matches_reference(scenario):
    apply_reference_payout(scenario, CATALOG, FX)
    items = [
        PayoutItem(i.ref, i.coverage, i.category, i.amount, i.currency, i.verdict, i.valuables)
        for i in scenario.items
    ]
    result = compute_payout(
        CATALOG.product(scenario.product),
        items,
        FX,
        prior_paid=scenario.policy.prior_paid,
        delay_hours=scenario.facts.get("delay_hours"),
    )
    assert result.total == scenario.expected_total_payout_eur
