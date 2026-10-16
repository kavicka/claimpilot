"""Build ClaimFacts from a claim's extractions: what the routing rules look at."""

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from claimpilot_core.domain import ClaimType, DocType
from claimpilot_core.fx import FxSnapshot, UnknownCurrencyError
from claimpilot_core.normalize import parse_amount, parse_currency
from claimpilot_core.schemas.documents import CRITICAL_FIELDS
from claimpilot_worker.extraction.extract import Extraction
from claimpilot_worker.ingest.injection_signals import Signal
from claimpilot_worker.routing.rules import ClaimFacts

CLAIM_TYPE_LABELS = {
    "liecebne naklady": ClaimType.MEDICAL,
    "uraz": ClaimType.ACCIDENT,
    "batozina": ClaimType.LUGGAGE,
    "oneskorenie batoziny": ClaimType.LUGGAGE,
    "storno cesty": ClaimType.CANCELLATION,
}
PRECEDENCE = [ClaimType.CANCELLATION, ClaimType.ACCIDENT, ClaimType.LUGGAGE, ClaimType.MEDICAL]


@dataclass
class DocInput:
    doc_type: DocType
    extraction: Extraction | None
    sha256: str
    redacted_text: str  # visible text only: hidden blocks never reach a model
    signals: list[Signal] = field(default_factory=list)  # prompt-injection signals


@dataclass
class History:
    """What earlier claims submitted: file hashes and invoice numbers, with their claim ids."""

    files: dict[str, str] = field(default_factory=dict)
    invoices: dict[str, str] = field(default_factory=dict)


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def claim_type_of(docs: list[DocInput]) -> ClaimType | None:
    from claimpilot_core.pii.guard import fold

    form = next(
        (d.extraction for d in docs if d.doc_type is DocType.CLAIM_FORM and d.extraction), None
    )
    found: set[ClaimType] = set()
    if form and (f := form.get("claim_types")) and f.value_raw:
        try:
            labels = json.loads(f.value_raw)
        except ValueError:
            labels = []
        found = {
            CLAIM_TYPE_LABELS[fold(x).strip()]
            for x in labels
            if fold(x).strip() in CLAIM_TYPE_LABELS
        }
    if not found:
        kinds = {d.doc_type for d in docs}
        if DocType.BOOKING_CONFIRMATION in kinds:
            found.add(ClaimType.CANCELLATION)
        elif kinds & {DocType.PROPERTY_IRREGULARITY_REPORT, DocType.POLICE_REPORT}:
            found.add(ClaimType.LUGGAGE)
        elif kinds & {DocType.MEDICAL_INVOICE, DocType.MEDICAL_REPORT}:
            found.add(ClaimType.MEDICAL)
    return next((t for t in PRECEDENCE if t in found), None)


def claimed_total_eur(docs: list[DocInput], fx: FxSnapshot) -> tuple[Decimal | None, bool]:
    """Sum of the claimed amounts in EUR, and whether every printed amount and its currency could
    be read. A row with no amount (the one-off fracture benefit) is skipped; a row whose currency
    cannot be read is left out of the sum, never counted as EUR."""
    form = next(
        (d.extraction for d in docs if d.doc_type is DocType.CLAIM_FORM and d.extraction), None
    )
    rows: list[tuple[str | None, str | None, str | None]] = []  # raw amount, amount, currency
    if form:
        names = {f.name.split("]")[0] for f in form.fields if f.name.startswith("claimed_items[")}
        rows = [
            (
                form.raw_value(f"{r}].amount"),
                form.value(f"{r}].amount"),
                form.value(f"{r}].currency"),
            )
            for r in names
        ]
    if not any(raw for raw, _, _ in rows):  # no claim form amounts: invoice and receipt totals
        rows = [
            (
                d.extraction.raw_value("total"),
                d.extraction.value("total"),
                d.extraction.value("currency"),
            )
            for d in docs
            if d.extraction and d.doc_type in (DocType.MEDICAL_INVOICE, DocType.PHARMACY_RECEIPT)
        ]
    total, seen, clear = Decimal(0), False, True
    for raw, value, raw_currency in rows:
        if not (raw or "").strip():
            continue
        amount, currency = parse_amount(value), parse_currency(raw_currency)
        if amount is None or currency is None:
            clear = False
            continue
        try:
            total += fx.to_eur(amount, currency)
            seen = True
        except UnknownCurrencyError:
            clear = False
    return (total if seen else None), clear and seen


def build_facts(
    docs: list[DocInput],
    fx: FxSnapshot,
    history: History,
    *,
    claim_id: str,
    policy_issue_date: date | None = None,
) -> ClaimFacts:
    claim_type = claim_type_of(docs)
    form = next(
        (d.extraction for d in docs if d.doc_type is DocType.CLAIM_FORM and d.extraction), None
    )
    report = next(
        (d.extraction for d in docs if d.doc_type is DocType.MEDICAL_REPORT and d.extraction), None
    )
    cert = next(
        (d.extraction for d in docs if d.doc_type is DocType.POLICY_CERTIFICATE and d.extraction),
        None,
    )
    issue = _date(cert.value("issue_date")) if cert else None
    dup_files = sorted(
        {
            history.files[d.sha256]
            for d in docs
            if d.sha256 in history.files and history.files[d.sha256] != claim_id
        }
    )
    dup_invoices = []
    for d in docs:
        if d.doc_type is DocType.MEDICAL_INVOICE and d.extraction:
            number = (d.extraction.value("invoice_number") or "").strip().upper()
            owner = history.invoices.get(number)
            if number and owner and owner != claim_id:
                dup_invoices.append(f"{number} ({owner})")
    critical = [
        f
        for d in docs
        if d.extraction
        for f in d.extraction.fields
        if f.name in CRITICAL_FIELDS.get(d.doc_type, []) and f.value_raw
    ]
    total, amounts_clear = claimed_total_eur(docs, fx)
    return ClaimFacts(
        claim_type=claim_type,
        doc_types=[d.doc_type for d in docs],
        claimed_total_eur=total,
        amounts_clear=amounts_clear,
        event_date=_date(form.value("event_date")) if form else None,
        report_visit_date=_date(report.value("visit_date")) if report else None,
        policy_issue_date=issue or policy_issue_date,
        duplicate_files=dup_files,
        duplicate_invoice_numbers=dup_invoices,
        report_texts=[d.redacted_text for d in docs if d.doc_type is DocType.MEDICAL_REPORT],
        critical_grounded=all(f.grounded for f in critical),
        min_critical_confidence=min((f.confidence for f in critical), default=0.0),
        injection=[
            # The document type, not the file name: a file name is the claimant's text too.
            f"{d.doc_type.value} p.{s.page}, {s.kind}: {s.quote}"
            for d in docs
            for s in d.signals
        ],
    )


def remember(docs: list[DocInput], history: History, claim_id: str) -> None:
    for d in docs:
        history.files.setdefault(d.sha256, claim_id)
        if d.doc_type is DocType.MEDICAL_INVOICE and d.extraction:
            number = (d.extraction.value("invoice_number") or "").strip().upper()
            if number:
                history.invoices.setdefault(number, claim_id)
