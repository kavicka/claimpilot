"""Payout engine, written before the implementation (ADR-002: money never runs in a prompt)."""

from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from claimpilot_core.domain import Coverage, CoverageVerdict, Product
from claimpilot_core.fx import FxSnapshot
from claimpilot_core.policy import load_products
from claimpilot_worker.coverage.payout import PayoutItem, compute_payout

ROOT = Path(__file__).resolve().parents[2]
CATALOG = load_products(ROOT / "data" / "policies" / "products.yaml")
FX = FxSnapshot.load(ROOT / "config" / "fx_rates.yaml")
C, N = CoverageVerdict.COVERED, CoverageVerdict.NOT_COVERED


def item(ref, cov, amount, currency="EUR", *, verdict=C, category="treatment", valuables=False):
    return PayoutItem(
        ref, Coverage(cov), category, Decimal(str(amount)), currency, verdict, valuables
    )


def pay(product, items, **kw):
    return compute_payout(CATALOG.product(product), items, FX, **kw)


def test_medical_one_deductible_per_event():
    r = pay(
        Product.BASIC,
        [item("I1", "medical", "279.50"), item("I2", "medical", "33.68", category="medication")],
    )
    assert r.total == Decimal("263.18")  # 313.18 - 50 deductible, once
    assert r.deductible == Decimal("50.00")
    assert sum(i.payout for i in r.items) == r.total


def test_foreign_currency_is_converted_with_the_snapshot():
    r = pay(Product.PREMIUM, [item("I1", "medical", "2450", "CZK")])
    assert r.total == Decimal("100.00")  # 2450 CZK / 24.50, premium has no deductible


def test_dental_capped_by_sublimit_before_deductible():
    r = pay(Product.BASIC, [item("I1", "medical", "410.00", category="dental")])
    assert r.total == Decimal("100.00")  # min(410, 150) - 50
    assert any("A4.4" in step for step in r.explanation)


def test_not_covered_items_pay_nothing():
    r = pay(Product.STANDARD, [item("I1", "medical", "800", verdict=N)])
    assert r.total == 0
    assert r.items[0].payout == 0


def test_medical_limit_minus_prior_payouts():
    r = pay(
        Product.BASIC,
        [item("I1", "medical", "70000")],
        prior_paid={Coverage.MEDICAL: Decimal("5000")},
    )
    assert r.total == Decimal(
        "55000.00"
    )  # limit 60 000 - 5 000 already paid; deductible inside the cap


def test_luggage_per_item_cap_valuables_share_and_deductible():
    items = [
        item("I1", "luggage", "260", category="luggage"),  # capped at 150 per item (Basic)
        item(
            "I2", "luggage", "900", category="valuables", valuables=True
        ),  # capped at 150 per item
        item("I3", "luggage", "100", category="luggage"),
    ]
    r = pay(Product.BASIC, items)
    # per item: 150 + 150 + 100 = 400; valuables (150) within 30 % of 500 = 150; minus deductible 30
    assert r.total == Decimal("370.00")


def test_luggage_valuables_share_caps_electronics():
    items = [
        item(f"I{i}", "luggage", "500", category="valuables", valuables=True) for i in range(3)
    ]
    r = pay(Product.PREMIUM, items)  # per item 500, valuables share 30 % of 2000 = 600
    assert r.total == Decimal("600.00")


def test_luggage_aggregate_limit_reached():
    r = pay(
        Product.STANDARD,
        [item("I1", "luggage", "290", category="luggage")],
        prior_paid={Coverage.LUGGAGE: Decimal("850")},
    )
    assert r.total == Decimal("150.00")  # remaining 1000 - 850, after the 20 deductible (270)


def test_delay_needs_more_than_minimum_hours():
    receipts = [
        item("I1", "delay", "40", category="essentials"),
        item("I2", "delay", "130", category="essentials"),
    ]
    assert pay(Product.STANDARD, receipts, delay_hours=12).total == 0
    assert pay(Product.STANDARD, receipts, delay_hours=13).total == Decimal(
        "150.00"
    )  # capped at limit


def test_basic_has_no_delay_or_cancellation_cover():
    r = pay(Product.BASIC, [item("I1", "cancellation", "500", category="cancellation_fee")])
    assert r.total == 0
    assert any("not included" in step for step in r.explanation)


def test_cancellation_80_percent_up_to_limit():
    assert pay(
        Product.STANDARD, [item("I1", "cancellation", "900", category="cancellation_fee")]
    ).total == Decimal("720.00")
    assert pay(
        Product.STANDARD, [item("I1", "cancellation", "2000", category="cancellation_fee")]
    ).total == Decimal("1000.00")


def test_fracture_benefit_is_fixed_and_paid_once():
    items = [
        item("I1", "accident", "0", category="fracture"),
        item("I2", "accident", "0", category="fracture"),
    ]
    assert pay(Product.STANDARD, items).total == Decimal("300.00")


def test_needs_review_items_are_held_not_paid():
    r = pay(Product.STANDARD, [item("I1", "medical", "500", verdict=CoverageVerdict.NEEDS_REVIEW)])
    assert r.total == 0
    assert r.held == Decimal("500.00")


def test_unknown_currency_raises():
    with pytest.raises(KeyError):
        pay(Product.STANDARD, [item("I1", "medical", "10", "XYZ")])


amounts = st.decimals(min_value=Decimal("0.01"), max_value=Decimal("90000"), places=2)
coverages = st.sampled_from(["medical", "luggage", "delay", "cancellation"])
verdicts = st.sampled_from([C, N, CoverageVerdict.NEEDS_REVIEW])


@settings(max_examples=300)
@given(
    product=st.sampled_from(list(Product)),
    rows=st.lists(st.tuples(coverages, amounts, verdicts, st.booleans()), min_size=1, max_size=8),
    prior=st.decimals(min_value=0, max_value=5000, places=2),
    hours=st.integers(0, 48),
)
def test_properties(product, rows, prior, hours):
    items = [
        item(
            f"I{i}", cov, amt, verdict=v, category="valuables" if val else "luggage", valuables=val
        )
        for i, (cov, amt, v, val) in enumerate(rows)
    ]
    prior_paid = {Coverage.MEDICAL: prior, Coverage.LUGGAGE: prior}
    r = pay(product, items, prior_paid=prior_paid, delay_hours=hours)
    terms = CATALOG.product(product)
    assert r.total >= 0
    assert sum(i.payout for i in r.items) == r.total
    for it in r.items:
        assert it.payout >= 0
        if it.verdict is not C:
            assert it.payout == 0
    for cov, paid in r.by_coverage.items():
        t = terms.coverage(cov)
        assert t is not None and t.limit is not None
        assert paid <= max(t.limit - prior_paid.get(cov, Decimal(0)), Decimal(0))
    claimed = sum((FX.to_eur(i.amount, i.currency) for i in items if i.verdict is C), Decimal(0))
    assert r.total <= claimed
