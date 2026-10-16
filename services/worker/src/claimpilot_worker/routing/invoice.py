"""Invoice routing: rules only, the most serious first.

  I1 fraud_review   the IBAN is not on the supplier's record
  I2 fraud_review   the same supplier and number arrived before
  I3 senior         text addressed to an AI system or hidden from the reader (R10 for claims)
  I4 senior         the supplier is not in the ERP
  I5 senior         a credit note (money goes back; no order to check it against)
  I6 senior         the amount is above the senior limit
  I7 standard       a line differs from the order or the receipt, or the order is unknown
  I8 standard       a validation check failed
  -  fast_track     everything checked out; a handler still approves with one click

The first hit decides the queue; every hit is kept for the review screen.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from claimpilot_core.domain import Queue

LINE_FINDINGS = {
    "price_diff", "short_delivery", "over_delivery", "not_ordered", "not_received",
    "unknown_order",
}  # fmt: skip
QUEUE_OF = {
    "I1": Queue.FRAUD_REVIEW,
    "I2": Queue.FRAUD_REVIEW,
    "I3": Queue.SENIOR,
    "I4": Queue.SENIOR,
    "I5": Queue.SENIOR,
    "I6": Queue.SENIOR,
    "I7": Queue.STANDARD,
    "I8": Queue.STANDARD,
}


@dataclass
class Hit:
    rule: str
    detail: str


@dataclass
class InvoiceRoute:
    queue: Queue
    rule: str | None
    hits: list[Hit] = field(default_factory=list)


def route_invoice(
    validation: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    *,
    kind: str,
    total: Decimal | None,
    senior_amount: Decimal,
    injection: list[str] | None = None,
) -> InvoiceRoute:
    kinds = {f["kind"] for f in findings}
    failed = [c for c in validation if not c["ok"]]
    hits: list[Hit] = []
    if "iban_changed" in kinds:
        hits.append(Hit("I1", "IBAN not on the supplier's record"))
    if any(c["name"] == "duplicate" for c in failed):
        dup = next(c for c in failed if c["name"] == "duplicate")
        hits.append(Hit("I2", f"same supplier and number as {dup.get('detail')}"))
    hits += [Hit("I3", d) for d in injection or []]
    if "unknown_supplier" in kinds:
        hits.append(Hit("I4", "supplier not in the ERP"))
    if kind == "credit_note":
        hits.append(Hit("I5", "credit note"))
    if total is not None and abs(total) > senior_amount:
        hits.append(Hit("I6", f"amount {total} above {senior_amount}"))
    line_findings = sorted(f["kind"] for f in findings if f["kind"] in LINE_FINDINGS)
    if line_findings:
        hits.append(Hit("I7", ", ".join(dict.fromkeys(line_findings))))
    checks = sorted({c["name"] for c in failed if c["name"] != "duplicate"})
    if checks:
        hits.append(Hit("I8", ", ".join(checks)))
    if not hits:
        return InvoiceRoute(Queue.FAST_TRACK, None, [])
    first = min(hits, key=lambda h: int(h.rule[1:]))
    return InvoiceRoute(QUEUE_OF[first.rule], first.rule, hits)
