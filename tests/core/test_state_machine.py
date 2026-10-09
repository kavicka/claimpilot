import itertools

import pytest

from claimpilot_core.domain import ClaimStatus as S
from claimpilot_core.state_machine import (
    ALLOWED,
    TERMINAL,
    Actor,
    InvalidTransitionError,
    can_transition,
    transition,
)

SYSTEM, HANDLER = Actor.SYSTEM, Actor.HANDLER

EXPECTED_ALLOWED = {
    (S.RECEIVED, S.PARSED, SYSTEM),
    (S.PARSED, S.REDACTED, SYSTEM),
    (S.REDACTED, S.EXTRACTED, SYSTEM),
    (S.EXTRACTED, S.ROUTED, SYSTEM),
    (S.EXTRACTED, S.NEEDS_INFO, SYSTEM),
    (S.ROUTED, S.ASSESSED, SYSTEM),
    (S.ROUTED, S.NEEDS_INFO, SYSTEM),
    (S.ASSESSED, S.IN_REVIEW, SYSTEM),
    (S.IN_REVIEW, S.APPROVED, HANDLER),
    (S.IN_REVIEW, S.REJECTED, HANDLER),
    (S.IN_REVIEW, S.NEEDS_INFO, HANDLER),
    (S.IN_REVIEW, S.EXTRACTED, HANDLER),  # reassess after corrections
    (S.APPROVED, S.SUBMITTED, SYSTEM),
    (S.NEEDS_INFO, S.RECEIVED, SYSTEM),
    (S.FAILED, S.RECEIVED, HANDLER),
    # Any pipeline step that exhausts its retries, and a submission that keeps failing.
    (S.RECEIVED, S.FAILED, SYSTEM),
    (S.PARSED, S.FAILED, SYSTEM),
    (S.REDACTED, S.FAILED, SYSTEM),
    (S.EXTRACTED, S.FAILED, SYSTEM),
    (S.ROUTED, S.FAILED, SYSTEM),
    (S.ASSESSED, S.FAILED, SYSTEM),
    (S.APPROVED, S.FAILED, SYSTEM),
}


def test_table_matches_the_documented_transitions():
    assert ALLOWED == EXPECTED_ALLOWED


@pytest.mark.parametrize(("src", "dst", "actor"), sorted(EXPECTED_ALLOWED))
def test_allowed_transition_returns_target(src, dst, actor):
    assert transition(src, dst, actor) is dst
    assert can_transition(src, dst, actor)


FORBIDDEN = [
    (src, dst, actor)
    for src, dst, actor in itertools.product(S, S, Actor)
    if (src, dst, actor) not in EXPECTED_ALLOWED
]


@pytest.mark.parametrize(("src", "dst", "actor"), FORBIDDEN)
def test_forbidden_transition_raises(src, dst, actor):
    assert not can_transition(src, dst, actor)
    with pytest.raises(InvalidTransitionError):
        transition(src, dst, actor)


def test_system_cannot_approve_or_reject():
    for dst in (S.APPROVED, S.REJECTED):
        with pytest.raises(InvalidTransitionError):
            transition(S.IN_REVIEW, dst, SYSTEM)


def test_terminal_states_have_no_exit():
    assert {S.SUBMITTED, S.REJECTED} == TERMINAL
    for src in TERMINAL:
        assert not any(s == src for s, _, _ in ALLOWED)


def test_every_non_terminal_state_has_an_exit():
    sources = {s for s, _, _ in ALLOWED}
    assert sources == set(S) - TERMINAL
