"""State machines, one per case kind.

Every status change in the system goes through one of them. The package root keeps the claim
machine's names (`transition`, `ALLOWED`, ...) so claim code reads as before; invoice code uses
`state_machine.invoices` or `for_kind`.
"""

from claimpilot_core.domain import CaseKind
from claimpilot_core.state_machine import claims, invoices
from claimpilot_core.state_machine.base import Actor, InvalidTransitionError, StateMachine
from claimpilot_core.state_machine.claims import ALLOWED, TERMINAL, can_transition, transition

_MACHINES: dict[CaseKind, StateMachine] = {
    CaseKind.CLAIM: claims.MACHINE,
    CaseKind.INVOICE: invoices.MACHINE,
}


def for_kind(kind: CaseKind | str) -> StateMachine:
    return _MACHINES[CaseKind(kind)]


__all__ = [
    "ALLOWED",
    "TERMINAL",
    "Actor",
    "InvalidTransitionError",
    "StateMachine",
    "can_transition",
    "claims",
    "for_kind",
    "invoices",
    "transition",
]
