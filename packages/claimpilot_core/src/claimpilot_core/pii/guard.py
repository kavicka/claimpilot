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

from claimpilot_core.identifiers import parse_rodne_cislo
from claimpilot_core.logging import register_secret
from claimpilot_core.pii.recognizers import BirthDateRecognizer, pattern_recognizers
from claimpilot_core.pii.tokens import TOKEN_PREFIX, TOKEN_RE, rehydrate

__all__ = ["TOKEN_RE", "ClaimRedactor", "Span", "fold", "rehydrate"]

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


# A ten-digit tax number (Slovak DIČ, a VAT id without its prefix) can pass the rodné číslo
# checksum; after its label it is a company's, not a person's.
TAX_LABEL_BEFORE = re.compile(
    r"(?:DI[ČC]|I[ČC]\s?DPH|VAT(?:\s?(?:ID|Reg\.?\s?No\.?))?|USt-?IdNr\.?|Tax\s?ID)\s*[:.]?\s*$",
    re.IGNORECASE,
)


def pattern_spans(text: str) -> list[Span]:
    out = []
    for rec in _recognizers():
        for r in rec.analyze(text, rec.supported_entities, None):
            if r.entity_type == "BIRTH_NUMBER" and TAX_LABEL_BEFORE.search(text[: r.start]):
                continue
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
            first, last = " ".join(parts[:-1]), parts[-1]
            out.add(" ".join(parts))
            out.add(f"{last}/{first}")  # PIR: SURNAME/FIRST
            out.add(f"{last} {first}")
            out.add(f"{last}, {first}")
            out.add(f"{first[0]}. {last}")
            if len(parts) == 2:  # Slovak and Czech decline names: "Jany Kováčovej"
                for fi in declined(first):
                    for la in declined(last):
                        out |= {f"{fi} {la}", f"{la} {fi}", f"{la}, {fi}"}
    if entity == "IBAN":
        from claimpilot_core.pii.recognizers import IbanRecognizerSk

        repaired = fold(IbanRecognizerSk.repair_ocr(value.upper()))
        out |= {repaired, " ".join(repaired[i : i + 4] for i in range(0, len(repaired), 4))}
    if entity == "BIRTH_DATE":
        out |= _date_forms(value)
    if entity in ("IBAN", "PHONE", "BIRTH_NUMBER"):
        compact = re.sub(r"[\s/]", "", f)
        out.add(compact)
        if entity == "IBAN":
            out.add(" ".join(compact[i : i + 4] for i in range(0, len(compact), 4)))
        if entity == "BIRTH_NUMBER" and len(compact) >= 9:
            out.add(f"{compact[:6]}/{compact[6:]}")
    return {v for v in out if len(v) >= 4}


MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def _date_forms(value: str) -> set[str]:
    """The printed forms one date of birth takes across the claim's documents and languages, so a
    birth date found after its label on one page is also replaced where it stands alone."""
    v = fold(value).strip().rstrip(".")
    if m := re.fullmatch(r"(\d{1,2})[./]\s?(\d{1,2})[./]\s?(\d{4})", v):
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", v):
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    elif (m := re.fullmatch(r"(\d{1,2})\s([a-z]{3})[a-z]*\.?\s(\d{4})", v)) and m[2] in MONTHS:
        d, mo, y = int(m[1]), MONTHS.index(m[2]) + 1, int(m[3])
    else:
        return set()
    if not (1 <= d <= 31 and 1 <= mo <= 12):
        return set()
    return {
        f"{d}. {mo}. {y}",
        f"{d}.{mo}.{y}",
        f"{d:02d}.{mo:02d}.{y}",
        f"{d:02d}/{mo:02d}/{y}",
        f"{mo:02d}/{d:02d}/{y}",
        f"{y}-{mo:02d}-{d:02d}",
        f"{d:02d} {MONTHS[mo - 1]} {y}",
    }


def declined(word: str) -> set[str]:
    """Slovak and Czech case forms of a folded name, by its ending. Heuristic and generous: a form
    is only ever matched as part of a full name, or after a form of address (see HONORIFIC)."""
    forms = {word}
    if len(word) < 3 or not word.isalpha():
        return forms
    if word.endswith("ova"):  # Kováčová -> Kováčovej, Kováčovú, Kováčovou
        forms |= {word[:-1] + e for e in ("ej", "u", "ou")}
    elif word.endswith("a"):  # Jana -> Jany, Jane, Janu, Janou; Sýkora -> Sýkoru, Sýkorovi
        forms |= {word[:-1] + e for e in ("y", "e", "u", "ou", "i", "ovi", "om")}
    elif word.endswith(("y", "i")):  # Hrubý -> Hrubého, Hrubému, Hrubým
        forms |= {word[:-1] + e for e in ("eho", "emu", "ym", "im")}
    elif word[-1] not in "aeiou":  # Novák -> Nováka, Novákovi, Novákom; Peter -> Petra
        stems = {word}
        if word[-2:] in ("er", "ek", "ec", "el") and len(word) > 4:
            stems.add(word[:-2] + word[-1])  # fleeting e
        forms |= {st + e for st in stems for e in ("a", "ovi", "om", "em", "e", "u")}
    return forms


# A surname on its own is matched only after a form of address ("pani Kováčová", "Frau Weber").
HONORIFIC = (
    r"(?:pani|panej|panu|pan|pana|panom|pane|frau|herr|herrn|mr|mrs|ms|"
    r"sig\.ra|sig\.|signora|signor|gospoda|gospodin|gospodo|g\.|p\.)"
)


def _person_key(value: str) -> frozenset[str]:
    titles = {"mr", "ms", "mrs", "mudr", "ing", "mgr", "dr"}
    return frozenset(p for p in re.split(r"[\s/.,]+", fold(value)) if p and p not in titles)


class ClaimRedactor:
    """Holds the token registry of one claim. Call `observe` on every text first, then `redact`."""

    def __init__(
        self, ner: NerFn | None = transformer_ner, *, keep: frozenset[str] = frozenset()
    ) -> None:
        """`keep`: entity types left readable. Invoices keep IBAN and ADDRESS: they are company
        data that the checks need (an IBAN changed against the supplier's record)."""
        self.ner = ner
        self.keep = keep
        self.entities: list[Entity] = []
        self._counters: dict[str, int] = {}

    @classmethod
    def from_mapping(
        cls, mapping: dict[str, tuple[str, str]], ner: NerFn | None = transformer_ner
    ) -> "ClaimRedactor":
        """A redactor that continues a claim's token registry (from the vault)."""
        r = cls(ner)
        for token, (entity, value) in mapping.items():
            r.entities.append(Entity(token, entity, value, _variants(entity, value)))
            prefix, n = token[1:-1].rsplit("_", 1)
            r._counters[prefix] = max(r._counters.get(prefix, 0), int(n))
        return r

    def tokenize(self, value: str) -> str:
        """A value read from a page image: OCR may have missed it, so detect entities in the value
        itself before replacing them."""
        self.observe([value])
        return self.redact(value)

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
        if entity == "BIRTH_NUMBER" and (rc := parse_rodne_cislo(value)):
            # A birth number holds the date of birth; whatever document prints that date, in
            # whatever form, gets the same token.
            b = rc.birth_date
            self._register("BIRTH_DATE", f"{b.day}. {b.month}. {b.year}")
        prefix = TOKEN_PREFIX[entity]
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        token = f"<{prefix}_{self._counters[prefix]}>"
        self.entities.append(Entity(token, entity, value, _variants(entity, value)))
        register_secret(value)

    def detect(self, text: str, *, ner: bool = True) -> list[Span]:
        spans = pattern_spans(text)
        if ner and self.ner is not None:
            spans += self.ner(text)
        return [s for s in spans if s.entity not in self.keep] if self.keep else spans

    def observe(self, texts: Iterable[str], *, ner: bool = True) -> None:
        """`ner=False`: identifiers by pattern only (e-mail, phone, IBAN, birth number), for text
        where the name model mistakes other words for people (product names)."""
        label_before = False
        for text in texts:
            for span in self.detect(text, ner=ner):
                self._register(span.entity, span.text)
            # OCR often splits a form cell into a label block ("GEB.") and a value block, or glues
            # the label to the end of the block before ("Podpis, pečiatka NAR.").
            if label_before and (m := BirthDateRecognizer.DATE_ANYWHERE.search(text)):
                self._register("BIRTH_DATE", m[1])
            label_before = bool(BirthDateRecognizer.LABEL_AT_END.search(text))

    def find(self, text: str) -> list[tuple[int, int, Entity]]:
        folded = fold(text)
        hits: list[tuple[int, int, Entity]] = []
        for e in self.entities:
            for v in sorted(e.variants, key=len, reverse=True):
                # A name may be broken across lines or spaced oddly by OCR.
                pattern = re.escape(v).replace(r"\ ", r"\s+")
                for m in re.finditer(rf"(?<![\w]){pattern}(?![\w])", folded):
                    hits.append((m.start(), m.end(), e))
            if e.entity == "PERSON":
                parts = [p for p in re.split(r"[\s/]+", fold(e.value)) if p]
                if len(parts) >= 2 and len(parts[-1]) >= 4:
                    forms = "|".join(
                        re.escape(f) for f in sorted(declined(parts[-1]), key=len, reverse=True)
                    )
                    for m in re.finditer(rf"(?<![\w]){HONORIFIC}\s+({forms})(?![\w])", folded):
                        hits.append((m.start(1), m.end(1), e))
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
