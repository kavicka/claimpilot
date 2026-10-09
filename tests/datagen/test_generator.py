"""Generator invariants: the dataset must be internally consistent before anything is scored on it."""

from collections import Counter
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from claimpilot_core.domain import ClaimStatus, CoverageVerdict, DocType, Queue
from claimpilot_core.fx import FxSnapshot
from claimpilot_core.identifiers import is_valid_iban, parse_rodne_cislo
from claimpilot_core.policy import load_products, load_terms
from claimpilot_datagen.reference import apply_reference_payout
from claimpilot_datagen.scenarios import FAST_TRACK_CAP_EUR, QUOTAS, SENIOR_THRESHOLD_EUR, Sampler

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def fx():
    return FxSnapshot.load(ROOT / "config" / "fx_rates.yaml")


@pytest.fixture(scope="module")
def scenarios(fx):
    catalog = load_products(ROOT / "data" / "policies" / "products.yaml")
    out = Sampler(42, fx).build()
    for s in out:
        apply_reference_payout(s, catalog, fx)
    return out


def claimed_eur(s, fx):
    return sum((fx.to_eur(i.amount, i.currency) for i in s.items), Decimal(0))


def test_quotas_per_split(scenarios):
    for split, plan in QUOTAS.items():
        got = Counter(s.archetype for s in scenarios if s.split == split)
        assert got == Counter(dict(plan)), split


def test_rare_queues_are_oversampled(scenarios):
    def count(split, queue):
        return sum(1 for s in scenarios if s.split == split and s.expected_queue is queue)

    assert count("dev", Queue.FRAUD_REVIEW) >= 10
    assert count("dev", Queue.SENIOR) >= 8
    assert count("test", Queue.FRAUD_REVIEW) >= 5
    assert count("test", Queue.SENIOR) >= 4


def test_at_least_30_percent_edge_cases(scenarios):
    routing_edges = {"missing_document", "duplicate_invoice", "date_inconsistency", "early_claim"}
    exclusions = {e for s in scenarios for e in s.edge_cases if e.startswith("exclusion_")}
    flagged = [
        s
        for s in scenarios
        if set(s.edge_cases)
        & (
            routing_edges
            | exclusions
            | {
                "above_product_limit",
                "aggregate_limit",
                "outside_policy_period",
                "outside_trip",
                "prompt_injection",
            }
        )
    ]
    assert len(flagged) / len(scenarios) >= 0.30


def test_identifiers_are_valid(scenarios):
    for s in scenarios:
        assert parse_rodne_cislo(s.person.birth_number) is not None
        assert is_valid_iban(s.person.iban)


def test_some_czech_birth_numbers_use_the_2004_offset(scenarios):
    offsets = [s for s in scenarios if s.person.czech and s.person.birth_date.year >= 2004]
    assert offsets, "no +20/+70 birth numbers in the dataset"


def test_invoice_totals_equal_line_sums(scenarios):
    for s in scenarios:
        for d in s.docs:
            if d.doc_type in (DocType.MEDICAL_INVOICE, DocType.PHARMACY_RECEIPT):
                item = next(i for i in s.items if i.doc_id == d.doc_id)
                assert item.amount == sum(ln.amount for ln in d.data["lines"]), s.scenario_id


def test_dates_are_ordered(scenarios):
    for s in scenarios:
        assert s.trip_start < s.trip_end
        assert s.policy.issue_date <= s.policy.start <= s.policy.end
        if s.archetype in ("outside_period", "outside_trip"):
            continue
        if s.claim_type.value == "cancellation":
            assert s.policy.issue_date < s.event_date < s.trip_start
            continue
        if s.archetype == "early_claim":
            assert s.policy.start <= s.event_date <= s.trip_end
            continue
        assert s.trip_start <= s.event_date <= s.trip_end, s.scenario_id
        assert s.policy.start <= s.event_date <= s.policy.end, s.scenario_id


def test_outside_cases_are_really_outside(scenarios):
    for s in scenarios:
        if s.archetype == "outside_period":
            assert s.event_date > s.policy.end
        if s.archetype == "outside_trip":
            assert s.event_date > s.trip_end
            assert s.policy.start <= s.event_date <= s.policy.end


def test_queue_thresholds_match_the_decision_table(scenarios, fx):
    for s in scenarios:
        total = claimed_eur(s, fx)
        if s.expected_queue is Queue.FAST_TRACK:
            assert total <= FAST_TRACK_CAP_EUR, s.scenario_id
            assert not any(d.scan for d in s.docs), s.scenario_id
        elif s.expected_rule == "R5":
            assert total > SENIOR_THRESHOLD_EUR, s.scenario_id
        elif s.expected_queue is not None:
            assert total > FAST_TRACK_CAP_EUR or s.expected_rule in (
                "R1",
                "R2",
                "R3",
                "R6",
                "R7",
            ), s.scenario_id


def test_early_claim_rule_r3_fires_only_on_early_claims(scenarios):
    for s in scenarios:
        early = s.event_date - s.policy.issue_date <= timedelta(days=3)
        assert early == (s.archetype == "early_claim"), s.scenario_id


def test_date_inconsistency_only_where_intended(scenarios):
    for s in scenarios:
        form = next(d for d in s.docs if d.doc_type is DocType.CLAIM_FORM)
        report = next((d for d in s.docs if d.doc_type is DocType.MEDICAL_REPORT), None)
        if report is None or s.claim_type.value == "cancellation":
            continue
        gap = abs((form.data["event_date"] - report.data["visit_date"]).days)
        if s.archetype == "date_inconsistency":
            assert gap > 2, s.scenario_id
        else:
            assert gap == 0, s.scenario_id


def test_duplicates_point_to_an_earlier_claim_in_the_same_split(scenarios):
    ids = [s.scenario_id for s in scenarios]
    by_id = {s.scenario_id: s for s in scenarios}
    dups = [s for s in scenarios if s.duplicate_of]
    assert len(dups) == 6
    for s in dups:
        original = by_id[s.duplicate_of]
        assert original.split == s.split
        assert ids.index(original.scenario_id) < ids.index(s.scenario_id)
        inv = next(d for d in s.docs if d.doc_type is DocType.MEDICAL_INVOICE)
        assert (inv.copy_of or inv.reprint_of).startswith(original.scenario_id)


def test_every_item_has_existing_clause_ids(scenarios):
    terms = load_terms(ROOT / "data" / "policies" / "vpp_cp_2026.yaml")
    for s in scenarios:
        for i in s.items:
            assert i.clause_ids, (s.scenario_id, i.ref)
            assert set(i.clause_ids) <= terms.clause_ids(), (s.scenario_id, i.clause_ids)


def test_payouts_exist_except_needs_info_and_are_never_negative(scenarios):
    for s in scenarios:
        if s.expected_status is ClaimStatus.NEEDS_INFO:
            assert s.expected_total_payout_eur is None
            continue
        assert s.expected_total_payout_eur is not None
        assert s.expected_total_payout_eur >= 0
        if all(i.verdict is CoverageVerdict.NOT_COVERED for i in s.items):
            assert s.expected_total_payout_eur == 0, s.scenario_id


def test_aggregate_limit_caps_the_payout(scenarios):
    s = next(x for x in scenarios if x.archetype == "luggage_aggregate_limit")
    limit = Decimal(1000 if s.product.value == "standard" else 2000)
    remaining = limit - s.policy.prior_paid[next(iter(s.policy.prior_paid))]
    assert s.expected_total_payout_eur <= remaining


def test_dental_is_capped_by_the_sublimit(scenarios):
    s = next(x for x in scenarios if x.archetype == "dental_over_sublimit")
    assert s.expected_total_payout_eur == Decimal(100)  # Basic: 150 sublimit - 50 deductible


def test_two_prompt_injections_one_per_split(scenarios):
    hits = [(s.split, d.doc_id) for s in scenarios for d in s.docs if d.injection]
    assert sorted(x for x, _ in hits) == ["dev", "test"]


def test_sampler_is_deterministic(fx):
    a = [
        (s.scenario_id, s.archetype, s.person.birth_number, str(s.items[0].amount))
        for s in Sampler(42, fx).build()
    ]
    b = [
        (s.scenario_id, s.archetype, s.person.birth_number, str(s.items[0].amount))
        for s in Sampler(42, fx).build()
    ]
    assert a == b
