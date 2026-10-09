"""PII guard: detect personal data in a claim's documents and replace it with typed tokens.

Detection = Presidio pattern recognizers (identifiers with checksums) + a multilingual NER model
for names. Every value found anywhere in the claim is then searched in every document of that claim,
diacritics- and case-insensitive and in known variants (PIR "SURNAME/FIRST", IBAN without spaces),
so a name the NER model missed on one page is still redacted if it was found on another.
Tokens are consistent per claim: the same person is <PERSON_1> on the invoice and the report.
"""

import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import lru_cache

from claimpilot_core.logging import register_secret
from claimpilot_core.pii.recognizers import pattern_recognizers

TOKEN_PREFIX = {
    "PERSON": "PERSON", "BIRTH_NUMBER": "RC", "IBAN": "IBAN", "PHONE": "PHONE",
    "EMAIL_ADDRESS": "EMAIL", "ADDRESS": "ADDRESS", "ID_CARD": "ID", "LICENCE_PLATE": "PLATE",
}  # fmt: skip
TOKEN_RE = re.compile(r"<(PERSON|RC|IBAN|PHONE|EMAIL|ADDRESS|ID|PLATE)_\d+>")
NER_MIN_SCORE = 0.75
# Form labels and common nouns the NER model mistakes for names ("Suma Mena" is a table header).
NOT_NAMES = {
    "suma", "mena", "popis", "dátum", "datum", "podpis", "hodinky", "poistený", "poistenie",
    "pacient", "patient", "paziente", "pacijent", "betrag", "importo", "iznos", "amount", "total",
}  # fmt: skip


def _fold_char(c: str) -> str:
    base = "".join(ch for ch in unicodedata.normalize("NFKD", c) if not unicodedata.combining(ch))
    return base.lower() if len(base) == 1 else c.lower()


def fold(text: str) -> str:
    """Lowercase without diacritics, same length as the input, so positions map one to one."""
    return "".join(_fold_char(c) for c in text)


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    entity: str
    text: str
    score: float
    source: str


@dataclass
class Entity:
    token: str
    entity: str
    value: str
    variants: set[str] = field(default_factory=set)  # folded strings to search for


NerFn = Callable[[str], list[Span]]


@lru_cache(maxsize=1)
def _ner_pipeline():
    import torch
    from transformers import pipeline

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    return pipeline(
        "token-classification",
        model="Babelscape/wikineural-multilingual-ner",
        aggregation_strategy="simple",
        device=device,
    )


def transformer_ner(text: str) -> list[Span]:
    spans = []
    for ent in _ner_pipeline()(text):
        if ent["entity_group"] != "PER" or float(ent["score"]) < NER_MIN_SCORE:
            continue
        start, end = int(ent["start"]), int(ent["end"])
        # Subword offsets can stop inside a word (seen after "Ä"); extend to whole words.
        while start > 0 and text[start - 1].isalpha():
            start -= 1
        while end < len(text) and text[end].isalpha():
            end += 1
        value = text[start:end].strip(" ,.:;")
        words = value.split()
        if (
            len(words) >= 2
            and all(w[:1].isupper() for w in words)
            and not any(fold(w) in NOT_NAMES for w in words)
        ):
            spans.append(
                Span(start, start + len(value), "PERSON", value, float(ent["score"]), "ner")
            )
    return spans


@lru_cache(maxsize=1)
def _recognizers():
    return pattern_recognizers()


def pattern_spans(text: str) -> list[Span]:
    out = []
    for rec in _recognizers():
        for r in rec.analyze(text, rec.supported_entities, None):
            out.append(
                Span(r.start, r.end, r.entity_type, text[r.start : r.end], r.score, "pattern")
            )
    return out


def _variants(entity: str, value: str) -> set[str]:
    f = fold(value).strip()
    out = {f}
    if entity == "PERSON":
        parts = [p for p in re.split(r"[\s/]+", f) if p]
        titles = {"mr", "ms", "mrs", "mudr.", "ing.", "mgr.", "dr."}
        parts = [p for p in parts if p not in titles]
        if len(parts) >= 2:
            out.add(" ".join(parts))
            out.add(f"{parts[-1]}/{' '.join(parts[:-1])}")  # PIR: SURNAME/FIRST
            out.add(f"{parts[-1]} {' '.join(parts[:-1])}")
    if entity == "IBAN":
        from claimpilot_core.pii.recognizers import IbanRecognizerSk

        repaired = fold(IbanRecognizerSk.repair_ocr(value.upper()))
        out |= {repaired, " ".join(repaired[i : i + 4] for i in range(0, len(repaired), 4))}
    if entity in ("IBAN", "PHONE", "BIRTH_NUMBER"):
        compact = re.sub(r"[\s/]", "", f)
        out.add(compact)
        if entity == "IBAN":
            out.add(" ".join(compact[i : i + 4] for i in range(0, len(compact), 4)))
        if entity == "BIRTH_NUMBER" and len(compact) >= 9:
            out.add(f"{compact[:6]}/{compact[6:]}")
    return {v for v in out if len(v) >= 4}


def _person_key(value: str) -> frozenset[str]:
    titles = {"mr", "ms", "mrs", "mudr", "ing", "mgr", "dr"}
    return frozenset(p for p in re.split(r"[\s/.,]+", fold(value)) if p and p not in titles)


class ClaimRedactor:
    """Holds the token registry of one claim. Call `observe` on every text first, then `redact`."""

    def __init__(self, ner: NerFn | None = transformer_ner) -> None:
        self.ner = ner
        self.entities: list[Entity] = []
        self._counters: dict[str, int] = {}

    def _register(self, entity: str, value: str) -> None:
        value = value.strip()
        if entity == "PERSON":
            key = _person_key(value)
            for e in self.entities:
                if e.entity == "PERSON" and _person_key(e.value) == key:
                    e.variants |= _variants(entity, value)
                    return
        else:
            folded = _variants(entity, value)
            for e in self.entities:
                if e.entity == entity and e.variants & folded:
                    e.variants |= folded
                    return
        prefix = TOKEN_PREFIX[entity]
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        token = f"<{prefix}_{self._counters[prefix]}>"
        self.entities.append(Entity(token, entity, value, _variants(entity, value)))
        register_secret(value)

    def detect(self, text: str) -> list[Span]:
        spans = pattern_spans(text)
        if self.ner is not None:
            spans += self.ner(text)
        return spans

    def observe(self, texts: Iterable[str]) -> None:
        for text in texts:
            for span in self.detect(text):
                self._register(span.entity, span.text)

    def find(self, text: str) -> list[tuple[int, int, Entity]]:
        folded = fold(text)
        hits: list[tuple[int, int, Entity]] = []
        for e in self.entities:
            for v in sorted(e.variants, key=len, reverse=True):
                for m in re.finditer(rf"(?<![\w]){re.escape(v)}(?![\w])", folded):
                    hits.append((m.start(), m.end(), e))
        hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
        merged: list[tuple[int, int, Entity]] = []
        for h in hits:
            if merged and h[0] < merged[-1][1]:
                continue  # overlaps a longer match that starts earlier
            merged.append(h)
        return merged

    def redact(self, text: str) -> str:
        out, last = [], 0
        for start, end, e in self.find(text):
            out.append(text[last:start])
            out.append(e.token)
            last = end
        out.append(text[last:])
        return "".join(out)

    def mapping(self) -> dict[str, tuple[str, str]]:
        """token -> (entity type, original value), for the vault."""
        return {e.token: (e.entity, e.value) for e in self.entities}


def rehydrate(text: str, mapping: dict[str, str]) -> str:
    return TOKEN_RE.sub(lambda m: mapping.get(m.group(0), m.group(0)), text)
