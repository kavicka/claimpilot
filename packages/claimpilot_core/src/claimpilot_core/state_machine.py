"""Claim state machine.

Every status change in the system goes through `transition`. The table is the single source of
truth for which moves exist and who may make them: the pipeline (system) moves a claim forward,
and only a handler approves, rejects or sends a claim back for more information.
"""

from enum import StrEnum
from itertools import pairwise

from claimpilot_core.domain import ClaimStatus as S


class Actor(StrEnum):
    SYSTEM = "system"
    HANDLER = "handler"


class InvalidTransitionError(ValueError):
    def __init__(self, src: S, dst: S, actor: Actor) -> None:
        super().__init__(f"{actor} cannot move a claim from {src} to {dst}")
        self.src, self.dst, self.actor = src, dst, actor


_PIPELINE = [S.RECEIVED, S.PARSED, S.REDACTED, S.EXTRACTED, S.ROUTED, S.ASSESSED, S.IN_REVIEW]

ALLOWED: frozenset[tuple[S, S, Actor]] = frozenset(
    {(a, b, Actor.SYSTEM) for a, b in pairwise(_PIPELINE)}
    # Unreadable files are found at ingest, missing documents after extraction or in routing.
    | {
        (S.RECEIVED, S.NEEDS_INFO, Actor.SYSTEM),
        (S.EXTRACTED, S.NEEDS_INFO, Actor.SYSTEM),
        (S.ROUTED, S.NEEDS_INFO, Actor.SYSTEM),
    }
    # Handler decisions.
    | {
        (S.IN_REVIEW, S.APPROVED, Actor.HANDLER),
        (S.IN_REVIEW, S.REJECTED, Actor.HANDLER),
        (S.IN_REVIEW, S.NEEDS_INFO, Actor.HANDLER),
        # After corrections the handler sends the claim back through routing and assessment;
        # extraction does not run again, so the corrections stay.
        (S.IN_REVIEW, S.EXTRACTED, Actor.HANDLER),
    }
    | {(S.APPROVED, S.SUBMITTED, Actor.SYSTEM)}
    # A new upload restarts the pipeline; a handler can retry a failed claim.
    | {(S.NEEDS_INFO, S.RECEIVED, Actor.SYSTEM), (S.FAILED, S.RECEIVED, Actor.HANDLER)}
    # A step that fails after its retries, or a submission that keeps failing.
    | {(s, S.FAILED, Actor.SYSTEM) for s in [*_PIPELINE[:-1], S.APPROVED]}
)

TERMINAL: frozenset[S] = frozenset({S.SUBMITTED, S.REJECTED})


def can_transition(src: S, dst: S, actor: Actor) -> bool:
    return (src, dst, actor) in ALLOWED


def transition(src: S, dst: S, actor: Actor) -> S:
    if not can_transition(src, dst, actor):
        raise InvalidTransitionError(src, dst, actor)
    return dst
