"""Checks across the documents of one claim, after each document is extracted.

They feed confidence and, later, the routing rules (a report dated days away from the claimed event
is a fraud signal, not an extraction error).
"""

from datetime import date

from claimpilot_core.domain import DocType
from claimpilot_core.pii.guard import TOKEN_RE
from claimpilot_worker.extraction.extract import Extraction, Field, score_confidence

PERSON_FIELDS = {"insured_name", "patient_name", "passenger_name", "complainant_name"}
MAX_DATE_GAP_DAYS = 2


def _first(extractions: list[Extraction], doc_type: DocType) -> Extraction | None:
    return next((e for e in extractions if e.doc_type is doc_type), None)


def _date(f: Field | None) -> date | None:
    if f is None or not f.value_norm:
        return None
    try:
        return date.fromisoformat(f.value_norm[:10])
    except ValueError:
        return None


def cross_document_checks(extractions: list[Extraction]) -> dict[str, bool]:
    results: dict[str, bool] = {}
    form = _first(extractions, DocType.CLAIM_FORM)
    cert = _first(extractions, DocType.POLICY_CERTIFICATE)
    report = _first(extractions, DocType.MEDICAL_REPORT)

    # One person across the claim: every name field carries the insured person's token.
    insured = form.get("insured_name") if form else None
    insured_token = TOKEN_RE.search(insured.value_raw or "") if insured else None
    if insured_token:
        for ex in extractions:
            for f in ex.fields:
                if f.name in PERSON_FIELDS and f.value_raw and ex is not form:
                    ok = insured_token.group(0) in f.value_raw
                    f.checks["same_person"] = ok
                    results["same_person"] = results.get("same_person", True) and ok

    if form:
        event = form.get("event_date")
        ev, start, end = _date(event), _date(form.get("trip_start")), _date(form.get("trip_end"))
        if event and ev and start and end:
            event.checks["event_in_trip"] = results["event_in_trip"] = start <= ev <= end
        if event and ev and cert:
            ps, pe = _date(cert.get("policy_start")), _date(cert.get("policy_end"))
            if ps and pe:
                event.checks["event_in_policy"] = results["event_in_policy"] = ps <= ev <= pe
        if event and ev and report:
            visit = _date(report.get("visit_date"))
            if visit:
                ok = abs((visit - ev).days) <= MAX_DATE_GAP_DAYS
                results["dates_consistent"] = ok
                # A gap is a fact about the claim, not an extraction error: record it, do not
                # lower confidence for it.
                event.checks.pop("dates_consistent", None)

    for ex in extractions:
        for f in ex.fields:
            f.confidence = score_confidence(f)
    return results
