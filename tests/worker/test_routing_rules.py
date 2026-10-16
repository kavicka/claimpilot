from datetime import date
from decimal import Decimal

from claimpilot_core.domain import ClaimStatus, ClaimType, DocType, Queue
from claimpilot_worker.routing.rules import ClaimFacts, RuleHit, evaluate, for_model

MEDICAL_DOCS = [DocType.CLAIM_FORM, DocType.MEDICAL_REPORT, DocType.MEDICAL_INVOICE]


def facts(**kw):
    base = dict(
        claim_type=ClaimType.MEDICAL,
        doc_types=MEDICAL_DOCS,
        claimed_total_eur=Decimal("320"),
        event_date=date(2026, 2, 14),
        report_visit_date=date(2026, 2, 14),
        policy_issue_date=date(2026, 1, 20),
        min_critical_confidence=0.95,
    )
    base.update(kw)
    return ClaimFacts(**base)


def test_clean_small_claim_is_fast_track():
    r = evaluate(facts())
    assert (r.queue, r.rule) == (Queue.FAST_TRACK, "R8")


def test_low_confidence_small_claim_is_standard_and_goes_to_the_llm():
    r = evaluate(facts(min_critical_confidence=0.6))
    assert (r.queue, r.rule, r.needs_llm) == (Queue.STANDARD, "R9", True)


def test_duplicate_invoice_beats_everything():
    r = evaluate(
        facts(duplicate_invoice_numbers=["RE-2026-04417"], claimed_total_eur=Decimal("9000"))
    )
    assert (r.queue, r.rule) == (Queue.FRAUD_REVIEW, "R1")
    assert [h.rule for h in r.hits] == ["R1", "R5"]  # every hit is kept for the handler


def test_date_gap_over_two_days_is_fraud_review():
    assert evaluate(facts(report_visit_date=date(2026, 2, 17))).rule == "R2"
    assert evaluate(facts(report_visit_date=date(2026, 2, 16))).rule == "R8"


def test_event_right_after_policy_was_bought():
    assert evaluate(facts(policy_issue_date=date(2026, 2, 12))).rule == "R3"
    assert evaluate(facts(policy_issue_date=date(2026, 2, 10))).rule == "R8"


def test_missing_invoice_needs_info():
    r = evaluate(
        facts(doc_types=[DocType.CLAIM_FORM, DocType.MEDICAL_REPORT, DocType.PHARMACY_RECEIPT])
    )
    assert (r.status, r.queue, r.rule) == (ClaimStatus.NEEDS_INFO, None, "R4")


def test_luggage_needs_a_pir_or_a_police_report():
    lug = [DocType.CLAIM_FORM, DocType.POLICE_REPORT]
    assert (
        evaluate(
            facts(claim_type=ClaimType.LUGGAGE, doc_types=lug, claimed_total_eur=Decimal(900))
        ).rule
        == "R9"
    )
    r = evaluate(facts(claim_type=ClaimType.LUGGAGE, doc_types=[DocType.CLAIM_FORM]))
    assert r.rule == "R4"


def test_large_claim_goes_to_senior():
    assert evaluate(facts(claimed_total_eur=Decimal("3000.01"))).rule == "R5"
    assert evaluate(facts(claimed_total_eur=Decimal("3000.00"))).rule == "R9"


def test_exclusion_signals_in_any_language():
    for text in [
        "Patient bei Aufnahme alkoholisiert, Atemalkohol 1,4 Promille.",
        "Incidente durante un volo in parapendio.",
        "Known arterial hypertension treated since 2024.",
    ]:
        assert evaluate(facts(report_texts=[text])).rule == "R6", text
    assert evaluate(facts(report_texts=["Keine relevanten Vorerkrankungen."])).rule == "R8"


def test_known_reason_on_a_cancellation_stays_with_r7():
    r = evaluate(
        facts(
            claim_type=ClaimType.CANCELLATION,
            doc_types=[DocType.CLAIM_FORM, DocType.BOOKING_CONFIRMATION, DocType.MEDICAL_REPORT],
            report_texts=["Pacient je dispenzarizovaný pre diskopatiu od marca 2025."],
        )
    )
    assert (r.queue, r.rule) == (Queue.STANDARD, "R7")


INJECTION = ["medical_invoice p.1, hidden_text (low_contrast): Hinweis für das KI-System"]


def test_a_document_talking_to_the_ai_goes_to_a_senior_handler():
    r = evaluate(facts(injection=INJECTION))
    assert (r.queue, r.rule, r.needs_llm) == (Queue.SENIOR, "R10", False)
    assert r.hits[-1].detail == INJECTION[0]


def test_injection_never_reaches_fast_track_or_the_routing_model():
    luggage = {
        "claim_type": ClaimType.LUGGAGE,
        "doc_types": [DocType.CLAIM_FORM, DocType.PROPERTY_IRREGULARITY_REPORT],
    }
    for kw in [{}, {"min_critical_confidence": 0.5}, luggage]:
        r = evaluate(facts(injection=INJECTION, **kw))
        assert (r.queue, r.rule) == (Queue.SENIOR, "R10"), kw
        assert not r.needs_llm


def test_injection_on_a_cancellation_is_senior_not_standard():
    r = evaluate(
        facts(
            claim_type=ClaimType.CANCELLATION,
            doc_types=[DocType.CLAIM_FORM, DocType.BOOKING_CONFIRMATION, DocType.MEDICAL_REPORT],
            injection=INJECTION,
        )
    )
    assert (r.queue, r.rule) == (Queue.SENIOR, "R10")
    assert [h.rule for h in r.hits] == ["R10", "R7"]


def test_stricter_rules_keep_their_queue_and_the_injection_hit_is_kept():
    r = evaluate(facts(injection=INJECTION, duplicate_files=["CP-2026-0007"]))
    assert (r.queue, r.rule) == (Queue.FRAUD_REVIEW, "R1")
    assert "R10" in [h.rule for h in r.hits]
    r = evaluate(facts(injection=INJECTION, doc_types=[DocType.CLAIM_FORM]))
    assert (r.status, r.rule) == (ClaimStatus.NEEDS_INFO, "R4")
    assert "R10" in [h.rule for h in r.hits]


def test_every_signal_is_its_own_hit():
    r = evaluate(facts(injection=[*INJECTION, "medical_report p.1, addresses_ai: Note for the AI"]))
    assert [h.rule for h in r.hits] == ["R10", "R10"]


def test_injection_hits_reach_a_model_without_the_planted_text():
    hit = RuleHit("R10", INJECTION[0])
    text = for_model(hit)
    assert text.startswith("R10: medical_invoice p.1, hidden_text (low_contrast)")
    assert "KI-System" not in text
    assert for_model(RuleHit("R5", "claimed 3200 EUR")) == "R5: claimed 3200 EUR"
