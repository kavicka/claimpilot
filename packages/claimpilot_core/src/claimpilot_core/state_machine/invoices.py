"""Invoice state machine.

Validation and matching sit between extraction and routing. Only a handler approves, and only an
approved invoice is exported to the ERP; a refused export goes back to review with its reason.
"""

from itertools import pairwise

from claimpilot_core.domain import CaseKind
from claimpilot_core.domain import InvoiceStatus as S
from claimpilot_core.state_machine.base import Actor, StateMachine

_PIPELINE = [
    S.RECEIVED,
    S.PARSED,
    S.REDACTED,
    S.EXTRACTED,
    S.VALIDATED,
    S.MATCHED,
    S.ROUTED,
    S.IN_REVIEW,
]

ALLOWED: frozenset[tuple[S, S, Actor]] = frozenset(
    {(a, b, Actor.SYSTEM) for a, b in pairwise(_PIPELINE)}
    # Unreadable file at ingest, missing pages in validation, unknown original in matching.
    | {
        (S.RECEIVED, S.NEEDS_INFO, Actor.SYSTEM),
        (S.EXTRACTED, S.NEEDS_INFO, Actor.SYSTEM),
        (S.VALIDATED, S.NEEDS_INFO, Actor.SYSTEM),
    }
    # Handler decisions; reassess runs validation, matching and routing again on the corrections.
    | {
        (S.IN_REVIEW, S.APPROVED, Actor.HANDLER),
        (S.IN_REVIEW, S.REJECTED, Actor.HANDLER),
        (S.IN_REVIEW, S.NEEDS_INFO, Actor.HANDLER),
        (S.IN_REVIEW, S.EXTRACTED, Actor.HANDLER),
    }
    | {(S.APPROVED, S.EXPORTED, Actor.SYSTEM), (S.APPROVED, S.IN_REVIEW, Actor.SYSTEM)}
    | {(S.NEEDS_INFO, S.RECEIVED, Actor.SYSTEM), (S.FAILED, S.RECEIVED, Actor.HANDLER)}
    | {(s, S.FAILED, Actor.SYSTEM) for s in [*_PIPELINE[:-1], S.APPROVED]}
)

TERMINAL: frozenset[S] = frozenset({S.EXPORTED, S.REJECTED})

MACHINE = StateMachine(CaseKind.INVOICE, ALLOWED, TERMINAL)
can_transition = MACHINE.can_transition
transition = MACHINE.transition
