import itertools

import pytest

from claimpilot_core.domain import CaseKind, ClaimStatus
from claimpilot_core.domain import InvoiceStatus as S
from claimpilot_core.state_machine import Actor, InvalidTransitionError, for_kind
from claimpilot_core.state_machine import claims as claim_machine
from claimpilot_core.state_machine import invoices as m

SYSTEM, HANDLER = Actor.SYSTEM, Actor.HANDLER

EXPECTED_ALLOWED = {
    (S.RECEIVED, S.PARSED, SYSTEM),
    (S.PARSED, S.REDACTED, SYSTEM),
    (S.REDACTED, S.EXTRACTED, SYSTEM),
    (S.EXTRACTED, S.VALIDATED, SYSTEM),
    (S.VALIDATED, S.MATCHED, SYSTEM),
    (S.MATCHED, S.ROUTED, SYSTEM),
    (S.ROUTED, S.IN_REVIEW, SYSTEM),
    (S.RECEIVED, S.NEEDS_INFO, SYSTEM),  # a file that cannot be opened
    (S.EXTRACTED, S.NEEDS_INFO, SYSTEM),  # validation: pages missing ("page 1 of 9")
    (S.VALIDATED, S.NEEDS_INFO, SYSTEM),  # matching: a credit note whose original is unknown
    (S.IN_REVIEW, S.APPROVED, HANDLER),
    (S.IN_REVIEW, S.REJECTED, HANDLER),
    (S.IN_REVIEW, S.NEEDS_INFO, HANDLER),
    (S.IN_REVIEW, S.EXTRACTED, HANDLER),  # reassess after corrections: validation runs again
    (S.APPROVED, S.EXPORTED, SYSTEM),
    (S.APPROVED, S.IN_REVIEW, SYSTEM),  # the ERP refused the UBL document; the reason is shown
    (S.NEEDS_INFO, S.RECEIVED, SYSTEM),
    (S.FAILED, S.RECEIVED, HANDLER),
    (S.RECEIVED, S.FAILED, SYSTEM),
    (S.PARSED, S.FAILED, SYSTEM),
    (S.REDACTED, S.FAILED, SYSTEM),
    (S.EXTRACTED, S.FAILED, SYSTEM),
    (S.VALIDATED, S.FAILED, SYSTEM),
    (S.MATCHED, S.FAILED, SYSTEM),
    (S.ROUTED, S.FAILED, SYSTEM),
    (S.APPROVED, S.FAILED, SYSTEM),
}


def test_table_matches_the_documented_transitions():
    assert m.ALLOWED == EXPECTED_ALLOWED


@pytest.mark.parametrize(("src", "dst", "actor"), sorted(EXPECTED_ALLOWED))
def test_allowed_transition_returns_target(src, dst, actor):
    assert m.transition(src, dst, actor) is dst
    assert m.can_transition(src, dst, actor)


FORBIDDEN = [
    (src, dst, actor)
    for src, dst, actor in itertools.product(S, S, Actor)
    if (src, dst, actor) not in EXPECTED_ALLOWED
]


@pytest.mark.parametrize(("src", "dst", "actor"), FORBIDDEN)
def test_forbidden_transition_raises(src, dst, actor):
    assert not m.can_transition(src, dst, actor)
    with pytest.raises(InvalidTransitionError, match="invoice"):
        m.transition(src, dst, actor)


def test_nothing_reaches_the_erp_without_a_handler():
    sources_of_approved = {s for s, d, _ in m.ALLOWED if d is S.APPROVED}
    assert sources_of_approved == {S.IN_REVIEW}
    assert all(a is HANDLER for _, d, a in m.ALLOWED if d is S.APPROVED)


def test_terminal_states_have_no_exit():
    assert {S.EXPORTED, S.REJECTED} == m.TERMINAL
    for src in m.TERMINAL:
        assert not any(s == src for s, _, _ in m.ALLOWED)


def test_every_non_terminal_state_has_an_exit():
    assert {s for s, _, _ in m.ALLOWED} == set(S) - m.TERMINAL


def test_for_kind_returns_the_machine_of_each_kind():
    assert for_kind(CaseKind.CLAIM) is claim_machine.MACHINE
    assert for_kind(CaseKind.INVOICE) is m.MACHINE


def test_a_claim_status_is_not_an_invoice_move():
    # SUBMITTED exists only for claims, EXPORTED only for invoices. Pyright refuses the mix;
    # statuses read from the database are plain strings, so the table refuses it too.
    with pytest.raises(ValueError, match="SUBMITTED"):
        m.transition(S.APPROVED, ClaimStatus.SUBMITTED, SYSTEM)  # pyright: ignore[reportArgumentType]
