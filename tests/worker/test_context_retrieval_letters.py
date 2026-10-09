"""Claim context helpers, rank fusion and the deterministic parts of the letters."""

from datetime import date
from decimal import Decimal

from claimpilot_core.domain import Coverage, DocType, Product
from claimpilot_worker.context import delay_hours, periods, prior_paid, product_of, to_date
from claimpilot_worker.coverage.retrieve import RRF_K, _fts_query, rrf
from claimpilot_worker.extraction.extract import Extraction, Field
from claimpilot_worker.routing.facts import DocInput
from claimpilot_worker.summaries.write import DecisionFacts, letter, sk_amount, sk_date

POLICY = {
    "product": "basic",
    "start": "2026-01-01",
    "end": "2026-12-31",
    "prior_paid": {"medical": "1200.00"},
}


def doc(doc_type: DocType, **norm: str) -> DocInput:
    fields = [Field(k, v, v, 1, value_norm=v) for k, v in norm.items()]
    return DocInput(doc_type, Extraction(doc_type, fields, {}, None, "test"), doc_type.value, "")


def test_to_date_accepts_datetimes_and_rejects_garbage():
    assert to_date("2026-02-14T09:30") == date(2026, 2, 14)
    assert to_date("14.02.2026") is None
    assert to_date(None) is None


def test_certificate_beats_the_policy_register():
    cert = doc(
        DocType.POLICY_CERTIFICATE,
        product_name="CestaPlus Premium",
        policy_start="2026-02-01",
        policy_end="2026-02-28",
    )
    form = doc(DocType.CLAIM_FORM, trip_start="2026-02-10", trip_end="2026-02-20")
    assert product_of([cert], POLICY) is Product.PREMIUM
    assert periods([cert, form], POLICY) == (
        (date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 2, 10), date(2026, 2, 20)),
    )


def test_register_fills_in_without_a_certificate():
    assert product_of([], POLICY) is Product.BASIC
    assert periods([], POLICY) == ((date(2026, 1, 1), date(2026, 12, 31)), None)
    assert prior_paid(POLICY) == {Coverage.MEDICAL: Decimal("1200.00")}
    assert prior_paid(None) == {}


def test_luggage_delay_in_whole_hours():
    pir = doc(
        DocType.PROPERTY_IRREGULARITY_REPORT,
        arrival_time="2026-02-14T10:15",
        delivery_time="2026-02-16T09:00",
    )
    assert delay_hours([pir]) == 46
    assert delay_hours([doc(DocType.PROPERTY_IRREGULARITY_REPORT, arrival_time="x")]) is None


def test_rrf_rewards_clauses_both_retrievers_found():
    vector = [("A4.1", "h", "t"), ("A5.2", "h", "t"), ("A3.2", "h", "t")]
    fts = [("A3.2", "h", "t"), ("A9.9", "h", "t")]
    ranked = rrf({"vector": vector, "fts": fts})
    assert ranked[0].clause_id == "A3.2"
    assert ranked[0].sources == ["vector", "fts"]
    assert ranked[0].score == 1 / (RRF_K + 3) + 1 / (RRF_K + 1)
    assert [h.clause_id for h in ranked[1:]] == ["A4.1", "A5.2", "A9.9"]


def test_fts_query_keeps_content_words_once():
    assert _fts_query("Ošetrenie a ošetrenie zlomeniny 2026") == "osetrenie | zlomeniny"
    assert _fts_query("a 1 2") == "x"


def test_slovak_number_and_date_formats():
    assert sk_amount(Decimal("12345.5")) == "12 345,50"
    assert sk_amount(Decimal("80")) == "80,00"
    assert sk_date(date(2026, 2, 4)) == "4. 2. 2026"


def facts(total: str, amount: Decimal | None = Decimal("279.50")) -> DecisionFacts:
    return DecisionFacts(
        reference="CP-2026-000001",
        product="Basic",
        claim_type="medical",
        event_date=date(2026, 2, 14),
        queue="standard",
        items=[
            {
                "description": "ošetrenie",
                "amount": amount,
                "currency": "EUR" if amount is not None else None,
                "verdict": "covered",
                "clauses": ["A4.1"],
                "payout": Decimal(total),
            }
        ],
        total_payout=Decimal(total),
        deductible=Decimal("50"),
        red_flags=[],
        missing=[],
        insured_token="<PERSON_1>",
    )


def test_letter_states_the_payout_from_code_not_from_the_model():
    body = letter(facts("229.50"), "Dôvody.")
    assert "vyplatí poistné plnenie 229,50 EUR" in body
    assert "neposkytne" in letter(facts("0"), "Dôvody.")


def test_unreadable_amount_is_said_plainly_to_the_writer():
    f = facts("0", amount=None)
    assert "nečitateľná" in f.as_prompt_json()
    assert f.check_facts().amounts == {Decimal("0"), Decimal("50")}


def test_claimed_totals_come_from_code():
    f = facts("42.27")
    f.items.append({**f.items[0], "amount": Decimal("20.50")})
    assert f.claimed_by_currency() == {"EUR": Decimal("300.00")}
    assert '"300,00 EUR"' in f.as_prompt_json()
    assert Decimal("300.00") in f.check_facts().amounts
