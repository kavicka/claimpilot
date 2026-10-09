"""Shared pieces for suites: run context, redacted claims, payload recording for leakage checks."""

from dataclasses import dataclass, field
from typing import Any

import httpx

from claimpilot_core.llm.cassette import CassetteMode
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.pii.guard import ClaimRedactor, fold
from claimpilot_core.schemas.parsing import ParsedDocument
from claimpilot_evals.cache import parsed
from claimpilot_evals.dataset import Dataset, GtClaim, GtDoc


class PayloadRecorder:
    """httpx event hook: keeps the body of every request the gateway sends to a model."""

    def __init__(self) -> None:
        self.payloads: list[str] = []

    async def __call__(self, request: httpx.Request) -> None:
        self.payloads.append(request.content.decode("utf-8", errors="replace"))

    def leaks(self, values: list[str]) -> list[str]:
        """Ground-truth PII values (exact or without diacritics) found in any payload."""
        import json

        texts = []
        for p in self.payloads:
            try:  # JSON escapes non-ASCII; decode so "Paška" is searched as written
                texts.append(json.dumps(json.loads(p), ensure_ascii=False))
            except ValueError:
                texts.append(p)
        found = []
        for v in values:
            fv = fold(v)
            if len(v) >= 4 and any(v in t or fv in fold(t) for t in texts):
                found.append(v)
        return found


@dataclass
class RunContext:
    split: str = "dev"
    limit: int | None = None
    overrides: dict[str, str] = field(default_factory=dict)
    cassette_mode: CassetteMode = CassetteMode.OFF
    options: dict[str, str] = field(default_factory=dict)
    dataset: Dataset = field(default_factory=Dataset)
    recorder: PayloadRecorder = field(default_factory=PayloadRecorder)
    _gateway: LLMGateway | None = None

    @property
    def gateway(self) -> LLMGateway:
        if self._gateway is None:
            self._gateway = LLMGateway(
                overrides=self.overrides,
                cassette_mode=self.cassette_mode,
                event_hooks={"request": [self.recorder]},
            )
        return self._gateway

    def claims(self) -> list[GtClaim]:
        return self.dataset.claims(self.split, self.limit)


@dataclass
class RedactedDoc:
    gt: GtDoc
    parsed: ParsedDocument
    redacted: dict[int, str]  # block seq -> redacted text

    def text(self, *, redacted: bool = True) -> str:
        blocks = self.parsed.blocks
        return "\n".join(self.redacted[b.seq] if redacted else b.text for b in blocks)


@dataclass
class RedactedClaim:
    gt: GtClaim
    docs: list[RedactedDoc]
    redactor: ClaimRedactor
    meta: dict[str, Any] = field(default_factory=dict)


def redact_claim(claim: GtClaim, redactor: ClaimRedactor | None = None) -> RedactedClaim:
    redactor = redactor or ClaimRedactor()
    docs = [(d, parsed(d.path, d.data["sha256"])) for d in claim.docs]
    redactor.observe(b.text for _, p in docs for b in p.blocks)
    out = [RedactedDoc(d, p, {b.seq: redactor.redact(b.text) for b in p.blocks}) for d, p in docs]
    return RedactedClaim(claim, out, redactor)
