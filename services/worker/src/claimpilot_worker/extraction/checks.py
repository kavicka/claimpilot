"""Checks on extracted values, registered per document type.

Every check runs in code and writes a named boolean into `Field.checks`; a failing check lowers
the field's confidence and keeps the case out of straight-through processing. Checks that hold
for any document (values parse, dates in order) run for every type; the rest are registered for
the document types they concern, so claims and invoices each bring their own.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from claimpilot_core.domain import DocType
from claimpilot_core.fields import kind_of
from claimpilot_core.identifiers import is_valid_iban, parse_rodne_cislo
from claimpilot_core.normalize import parse_amount
from claimpilot_core.pii.guard import rehydrate

if TYPE_CHECKING:
    from claimpilot_worker.extraction.extract import Field

# (fields by name, all fields, token -> value) -> None; writes into Field.checks
Check = Callable[[dict[str, "Field"], list["Field"], dict[str, str]], None]

CHECKS: dict[DocType, list[Check]] = {}

DATE_PAIRS = [
    ("trip_start", "trip_end"),
    ("policy_start", "policy_end"),
    ("service_date", "issue_date"),
    ("visit_date", "discharge_date"),
    ("arrival_time", "delivery_time"),
]


def check(*doc_types: DocType) -> Callable[[Check], Check]:
    def deco(fn: Check) -> Check:
        for t in doc_types:
            CHECKS.setdefault(t, []).append(fn)
        return fn

    return deco


def run_checks(doc_type: DocType, fields: list["Field"], mapping: dict[str, str]) -> None:
    by_name = {f.name: f for f in fields}
    for f in fields:
        if f.value_raw is None:
            continue
        if kind_of(f.name) != "text":
            f.checks["parses"] = f.value_norm is not None
    for fn in CHECKS.get(doc_type, []):
        fn(by_name, fields, mapping)
    for a, b in DATE_PAIRS:
        fa, fb = by_name.get(a), by_name.get(b)
        if fa and fb and fa.value_norm and fb.value_norm:
            ok = fa.value_norm[:10] <= fb.value_norm[:10]
            fa.checks["date_order"] = ok
            fb.checks["date_order"] = ok


# --- claims -------------------------------------------------------------------------------


@check(DocType.MEDICAL_INVOICE, DocType.PHARMACY_RECEIPT)
def total_matches_lines(
    by_name: dict[str, "Field"], fields: list["Field"], mapping: dict[str, str]
) -> None:
    total = by_name.get("total")
    lines = [f for f in fields if f.name.startswith("line_items[") and f.name.endswith(".amount")]
    if not (total and total.value_norm and lines):
        return
    amounts = [parse_amount(f.value_norm) for f in lines]
    if any(a is None for a in amounts):
        return
    ok = (
        abs(sum(a for a in amounts if a is not None) - (parse_amount(total.value_norm) or 0))
        <= 0.01
    )
    total.checks["total_matches_lines"] = ok
    for f in lines:
        f.checks["total_matches_lines"] = ok


@check(DocType.CLAIM_FORM)
def claim_form_identifiers(
    by_name: dict[str, "Field"], fields: list["Field"], mapping: dict[str, str]
) -> None:
    if (f := by_name.get("iban")) and f.value_raw:
        f.checks["iban_checksum"] = is_valid_iban(rehydrate(f.value_raw, mapping))
    if (f := by_name.get("insured_birth_number")) and f.value_raw:
        f.checks["birth_number_valid"] = (
            parse_rodne_cislo(rehydrate(f.value_raw, mapping)) is not None
        )
