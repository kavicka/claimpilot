"""A state machine is a table of allowed moves (from, to, actor); nothing else decides."""

from collections.abc import Iterable
from enum import StrEnum

from claimpilot_core.domain import CaseKind

_NOUN = {CaseKind.CLAIM: "a claim", CaseKind.INVOICE: "an invoice"}


class Actor(StrEnum):
    SYSTEM = "system"
    HANDLER = "handler"


class InvalidTransitionError(ValueError):
    def __init__(self, kind: CaseKind, src: StrEnum, dst: StrEnum, actor: Actor) -> None:
        super().__init__(f"{actor} cannot move {_NOUN[kind]} from {src} to {dst}")
        self.kind, self.src, self.dst, self.actor = kind, src, dst, actor


class StateMachine[S: StrEnum]:
    def __init__(
        self,
        kind: CaseKind,
        allowed: Iterable[tuple[S, S, Actor]],
        terminal: Iterable[S],
    ) -> None:
        self.kind = kind
        self.allowed: frozenset[tuple[S, S, Actor]] = frozenset(allowed)
        self.terminal: frozenset[S] = frozenset(terminal)

    def can_transition(self, src: S, dst: S, actor: Actor) -> bool:
        return (src, dst, actor) in self.allowed

    def transition(self, src: S, dst: S, actor: Actor) -> S:
        if not self.can_transition(src, dst, actor):
            raise InvalidTransitionError(self.kind, src, dst, actor)
        return dst
