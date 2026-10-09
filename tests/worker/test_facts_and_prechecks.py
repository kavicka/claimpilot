"""Facts the routing rules read, and the coverage prechecks that decide items without a model."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from claimpilot_core.domain import ClaimType, Coverage, CoverageVerdict, DocType, Queue
from claimpilot_core.fields import normalize
from claimpilot_core.fx import default_fx
from claimpilot_worker.coverage.decide import ClaimItem, items_from_claim, precheck, readable
from claimpilot_worker.extraction.extract import Extraction, Field
from claimpilot_worker.routing.facts import DocInput, History, build_facts, claimed_total_eur
from claimpilot_worker.routing.rules import evaluate

ROOT = Path(__file__).resolve().parents[2]
FX = default_fx(ROOT / "config")


def doc(doc_type: DocType, sha: str = "a", **values: str | None) -> DocInput:
    fields = [
        Field(
            name,
            value,
            value,
            1,
            grounded=True,
            value_norm=normalize(name, value) if value else None,
            confidence=0.97,
        )
        for name, value in values.items()
    ]
    return DocInput(doc_type, Extraction(doc_type, fields, {}, None, "test"), sha, "")


def form(*rows: tuple[str | None, str | None], **values: str | None) -> DocInput:
    items: dict[str, str | None] = {}
    for i, (amount, currency) in enumerate(rows):
        items[f"claimed_items[{i}].description"] = f"item {i}"
        items[f"claimed_items[{i}].amount"] = amount
        items[f"claimed_items[{i}].currency"] = currency
    return doc(DocType.CLAIM_FORM, "form", event_date="14.02.2026", **values, **items)


def test_total_converts_each_row_to_eur():
    total, clear = claimed_total_eur([form(("100,00", "EUR"), ("2 450", "CZK"))], FX)
    assert (total, clear) == (Decimal("200.00"), True)


def test_missing_currency_is_not_counted_as_eur():
    total, clear = claimed_total_eur([form(("100,00", "EUR"), ("2 450", None))], FX)
    assert (total, clear) == (Decimal("100.00"), False)


def test_unknown_currency_and_unreadable_amount_are_unclear():
    assert claimed_total_eur([form(("100", "THB"))], FX) == (None, False)
    assert claimed_total_eur([form(("ilegible", "EUR"))], FX) == (None, False)


def test_invoice_totals_are_the_fallback_without_a_claim_form():
    invoice = doc(DocType.MEDICAL_INVOICE, total="279,50", currency="EUR")
    assert claimed_total_eur([invoice], FX) == (Decimal("279.50"), True)


def test_small_claim_with_an_unclear_amount_is_not_fast_tracked():
    docs = [
        form(("120", None)),
        doc(DocType.MEDICAL_REPORT, "r", visit_date="14.02.2026"),
        doc(DocType.MEDICAL_INVOICE, "i", total="120", currency=None),
    ]
    facts = build_facts(docs, FX, History(), claim_id="c1")
    assert facts.claim_type is ClaimType.MEDICAL
    assert facts.amounts_clear is False
    assert evaluate(facts).queue is not Queue.FAST_TRACK


def test_duplicates_from_other_claims_are_found_but_not_the_claim_itself():
    history = History(files={"same": "c0", "own": "c1"}, invoices={"RE-1": "c0"})
    docs = [
        doc(DocType.MEDICAL_INVOICE, "same", invoice_number="re-1"),
        doc(DocType.MEDICAL_REPORT, "own"),
    ]
    facts = build_facts(docs, FX, history, claim_id="c1")
    assert facts.duplicate_files == ["c0"]
    assert facts.duplicate_invoice_numbers == ["RE-1 (c0)"]


def test_items_keep_unreadable_values_as_none():
    items = items_from_claim([form(("80", "EUR"), (None, "EUR"))])
    assert [(i.amount, i.currency) for i in items] == [(Decimal("80"), "EUR"), (None, "EUR")]


def item(amount: str | None = "80", currency: str | None = "EUR", **kw) -> ClaimItem:
    return ClaimItem("I1", "x", Decimal(amount) if amount else None, currency, **kw)


def check(it: ClaimItem, **kw) -> bool:
    args = dict(event=date(2026, 2, 14), policy=None, trip=None, duplicate=False)
    args.update(kw)
    return precheck(it, known_currencies=set(FX.rates), **args)


def test_unreadable_amount_or_currency_goes_to_a_handler():
    for it in (item(amount=None), item(currency=None), item(currency="THB")):
        assert check(it) is True
        assert it.verdict is CoverageVerdict.NEEDS_REVIEW
        assert readable(it, FX) == (Decimal(0), "EUR")


def test_event_outside_the_policy_or_trip_is_not_covered():
    it = item(coverage=Coverage.MEDICAL)
    assert check(it, policy=(date(2026, 3, 1), date(2026, 3, 31))) is True
    assert (it.verdict, it.clause_ids) == (CoverageVerdict.NOT_COVERED, ["A3.2"])
    it = item(coverage=Coverage.MEDICAL)
    assert check(it, trip=(date(2026, 2, 1), date(2026, 2, 10))) is True
    assert it.clause_ids == ["A3.3"]


def test_cancellation_happens_before_the_trip_so_the_trip_check_skips_it():
    it = item(coverage=Coverage.CANCELLATION)
    assert check(it, trip=(date(2026, 3, 1), date(2026, 3, 10))) is False


def test_duplicate_invoice_is_not_paid_twice():
    it = item(coverage=Coverage.MEDICAL)
    assert check(it, duplicate=True) is True
    assert it.clause_ids == ["A13.4"]


def test_clear_item_inside_all_periods_goes_to_the_model():
    assert check(item(coverage=Coverage.MEDICAL)) is False


def test_fracture_benefit_row_without_amount_is_not_unclear():
    total, clear = claimed_total_eur([form(("100,00", "EUR"), (None, None))], FX)
    assert (total, clear) == (Decimal("100.00"), True)
    it = item(amount=None, currency=None, coverage=Coverage.ACCIDENT)
    assert check(it) is False  # goes on to the model; the payout engine pays the fixed benefit


def test_cancellation_is_judged_against_the_issue_date_not_the_trip():
    trip = (date(2026, 3, 1), date(2026, 3, 10))
    it = item(coverage=Coverage.CANCELLATION)
    assert check(it, policy=trip, trip=trip, issued=date(2026, 1, 5)) is False
    it = item(coverage=Coverage.CANCELLATION)
    assert check(it, policy=trip, trip=trip, issued=date(2026, 2, 20)) is True
    assert (it.verdict, it.clause_ids) == (CoverageVerdict.NOT_COVERED, ["A9.4"])


def test_general_exclusions_are_always_offered():
    from claimpilot_worker.coverage.decide import general_exclusions

    assert [h.clause_id for h in general_exclusions()] == ["A11.1", "A11.2", "A11.3", "A11.4"]
