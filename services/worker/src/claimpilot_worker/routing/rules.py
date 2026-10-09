"""Routing rules (ADR-005): deterministic rules decide first, in config/routing.yaml order."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from claimpilot_core.domain import ClaimStatus, ClaimType, DocType, Queue
from claimpilot_core.pii.guard import fold
from claimpilot_core.settings import get_settings


@dataclass
class ClaimFacts:
    claim_type: ClaimType | None
    doc_types: list[DocType]
    claimed_total_eur: Decimal | None = None
    amounts_clear: bool = True  # every claimed amount and currency was read
    event_date: date | None = None
    report_visit_date: date | None = None
    policy_issue_date: date | None = None
    duplicate_files: list[str] = field(default_factory=list)
    duplicate_invoice_numbers: list[str] = field(default_factory=list)
    report_texts: list[str] = field(default_factory=list)
    critical_grounded: bool = True
    min_critical_confidence: float = 1.0


@dataclass
class RuleHit:
    rule: str
    detail: str


@dataclass
class RoutingResult:
    queue: Queue | None
    status: ClaimStatus
    rule: str
    hits: list[RuleHit]
    needs_llm: bool = False

    def hits_json(self) -> list[dict[str, Any]]:
        return [{"rule": h.rule, "detail": h.detail} for h in self.hits]


@lru_cache
def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or get_settings().config_dir / "routing.yaml"
    return yaml.safe_load(path.read_text("utf-8"))


def exclusion_signals(texts: list[str], signals: dict[str, list[str]]) -> list[str]:
    joined = fold(" ".join(texts))
    return [name for name, words in signals.items() if any(fold(w) in joined for w in words)]


def missing_documents(
    claim_type: ClaimType | None, doc_types: list[DocType], cfg: dict
) -> list[str]:
    if claim_type is None:
        return ["claim_form"] if DocType.CLAIM_FORM not in doc_types else []
    present = {d.value for d in doc_types}
    missing = []
    for alternatives in cfg["required_documents"][claim_type.value]:
        if not present.intersection(alternatives):
            missing.append(" or ".join(alternatives))
    return missing


def evaluate(facts: ClaimFacts, cfg: dict | None = None) -> RoutingResult:
    """All rules are evaluated so the handler sees every hit; the first in order decides."""
    cfg = cfg or load_config()
    th = cfg["thresholds"]
    hits: list[RuleHit] = []
    if facts.duplicate_files:
        hits.append(RuleHit("R1", f"file already submitted in {', '.join(facts.duplicate_files)}"))
    if facts.duplicate_invoice_numbers:
        hits.append(
            RuleHit(
                "R1",
                f"invoice number already claimed: {', '.join(facts.duplicate_invoice_numbers)}",
            )
        )
    if facts.event_date and facts.report_visit_date:
        gap = abs((facts.report_visit_date - facts.event_date).days)
        if gap > th["date_gap_days"]:
            hits.append(
                RuleHit(
                    "R2",
                    f"claim form says {facts.event_date}, medical report "
                    f"{facts.report_visit_date} ({gap} days)",
                )
            )
    if facts.event_date and facts.policy_issue_date:
        days = (facts.event_date - facts.policy_issue_date).days
        if 0 <= days <= th["early_claim_days"]:
            hits.append(RuleHit("R3", f"event {days} day(s) after the policy was concluded"))
    missing = missing_documents(facts.claim_type, facts.doc_types, cfg)
    if missing:
        hits.append(RuleHit("R4", f"missing: {', '.join(missing)}"))
    total = facts.claimed_total_eur
    if total is not None and total > th["senior_min_eur"]:
        hits.append(RuleHit("R5", f"claimed {total} EUR, above {th['senior_min_eur']} EUR"))
    medical_like = facts.claim_type in (ClaimType.MEDICAL, ClaimType.ACCIDENT)
    signals = exclusion_signals(facts.report_texts, cfg["signals"]) if medical_like else []
    if signals:
        hits.append(RuleHit("R6", f"medical report mentions: {', '.join(signals)}"))
    if facts.claim_type is ClaimType.CANCELLATION:
        hits.append(RuleHit("R7", "cancellation claim"))

    first = hits[0].rule if hits else None
    if first in ("R1", "R2", "R3"):
        return RoutingResult(Queue.FRAUD_REVIEW, ClaimStatus.ROUTED, first, hits)
    if first == "R4":
        return RoutingResult(None, ClaimStatus.NEEDS_INFO, "R4", hits)
    if first in ("R5", "R6"):
        return RoutingResult(Queue.SENIOR, ClaimStatus.ROUTED, first, hits)
    if first == "R7":
        return RoutingResult(Queue.STANDARD, ClaimStatus.ROUTED, "R7", hits)
    fast = (
        total is not None
        and facts.amounts_clear
        and total <= th["fast_track_max_eur"]
        and facts.critical_grounded
        and facts.min_critical_confidence >= th["fast_track_min_confidence"]
        and facts.claim_type in (ClaimType.MEDICAL, ClaimType.LUGGAGE)
    )
    if fast:
        hits.append(RuleHit("R8", f"{total} EUR, every critical field grounded"))
        return RoutingResult(Queue.FAST_TRACK, ClaimStatus.ROUTED, "R8", hits)
    return RoutingResult(Queue.STANDARD, ClaimStatus.ROUTED, "R9", hits, needs_llm=True)
