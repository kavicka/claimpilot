"""Prompt-injection signals: document text that addresses a model, tells it to drop its rules,
imitates its answer or our prompt markup, or names our internal labels.

Ordinary claim documents (invoices, medical reports, police reports, airline forms) never talk to
an AI system, so these patterns are narrow on purpose: a hit sends the claim to a senior handler
(routing rule R10) and keeps the coverage model from deciding in its favour. The patterns run on
folded text (lowercase, no diacritics) in the dataset's languages: Slovak, Czech, German, Italian,
Croatian, English. OCR reads "AI" as "Al" or "A1", so those count too where the context is clear.

A miss is not a pass: the prompts still treat documents as data, and code still decides.
"""

import re
from dataclasses import dataclass

from claimpilot_core.pii.guard import fold
from claimpilot_core.schemas.parsing import ParsedDocument

QUOTE_CHARS = 120

_AI = r"(?:ai|a\.i\.|ki|ia|a[l1])"
_AI_NOUNS = (
    # not the Italian "sistema": "al sistema sanitario" is ordinary Italian
    r"(?:system|systems|systeme?|systemu|sustav\w*|model\w*|assistant\w*|"
    r"asistent\w*|agent\w*|reviewer|bot)"
)
_TO = r"(?:pre|pro|za|fur|an|per|for|to|al|alla)"
_ARTICLE = r"(?:(?:das|die|den|dem|the|il|lo|la|l')\s+)?"

PATTERNS: dict[str, list[str]] = {
    "addresses_ai": [
        # "Note for the AI", "Pokyn pre AI", "Napomena za AI sustav", "Hinweis für das KI-System"
        rf"\b(?:pokyn\w*|poznamk\w*|napomen\w*|hinweis\w*|anweisung\w*|nota|note|notice|"
        rf"istruzion\w*|uput\w*|instruction\w*|message|zprava|sprava|poruk\w*|mitteilung)\s+"
        rf"{_TO}\s+{_ARTICLE}(?:{_AI}\b|umel\w*|umjetn\w*|kunstlich\w*|automat\w*|"
        rf"sistema\s+(?:di\s+)?{_AI}\b|{_AI_NOUNS}\b)",
        rf"\b{_AI}[\s-]+{_AI_NOUNS}\b",
        r"\bsistema\s+(?:di\s+)?(?:ia|ai)\b",
        r"\b(?:for|to|dear|attention|attn)\s+(?:the\s+|all\s+|any\s+)?(?:ai|a\.i\.|"
        r"artificial intelligence|language models?|llms?|chatbots?|automated\s+\w+)\b",
        r"\b(?:umel\w*\s+inteligenc\w*|kunstlich\w*\s+intelligenz|intelligenza\s+artificiale|"
        r"umjetn\w*\s+inteligencij\w*|artificial\s+intelligence|sprachmodell\w*|"
        r"jazykov\w*\s+model\w*|language\s+models?|modell\w*\s+linguistic\w*)\b",
        r"\b(?:chatgpt|gpt-?\d\w*|openai|anthropic|llm)\b",
    ],
    "override": [
        r"\b(?:ignore|ignoruj\w*|ignorier\w*|ignora\w*|ignoriraj\w*|zanemari\w*|disregard|forget|"
        r"zabudni\w*|zabudnite|zapomen\w*|vergiss|vergessen|dimentica\w*|zaboravi\w*|override)\b"
        r"[^.\n]{0,40}?\b(?:instructions?|rules?|prompts?|pokyn\w*|pravidl\w*|pravil\w*|"
        r"anweisung\w*|regeln?|vorgaben?|istruzion\w*|regol\w*|upute|uputa|uputstv\w*|"
        r"guidelines?|previous|above|prior|predchadz\w*|predchoz\w*|vorherig\w*|obigen?|"
        r"precedent\w*|prethodn\w*)\b",
    ],
    "role_marker": [
        r"(?:^|\n)\s*(?:system|assistant|user|human)\s*:",
        r"<\|(?:im_start|im_end|system|user|assistant|endoftext)\|>",
        r"\[/?inst\]|<<\s*/?sys\s*>>|</?(?:system|instructions?)>",
    ],
    "delimiter": [r"<<<|>>>", r"={3,}\s*page\s+\d+\s*={3,}", r"```"],
    "fake_answer": [
        r"\"(?:confidence|grounded|verdict|queue|clause_ids|quote|rationale|value_raw|payout\w*|"
        r"total|currency|status)\"\s*:",
    ],
    "internal_label": [
        r"\b(?:fast_track|fraud_review|needs_review|not_covered|needs_info|needs_handler)\b",
    ],
    "steering": [
        r"\b(?:approve|approva\w*|genehmigen\s+sie|schvalte|odobrite|odobri)\s+(?:every|all|it|"
        r"ihn|ihm|tutt\w*|vsetk\w*|vsech\w*|sve|svaki|zahtjev|this\s+claim|the\s+claim)\b",
        r"\b(?:pay|isplati\w*|zaplat\w*|zahlen\s+sie)\b[^.\n]{0,20}\b(?:double|twice|dvostruk\w*|"
        r"dvojnasob\w*|doppelt\w*|doppio)\b",
        r"\bdouble\s+the\s+(?:amount|payout|sum)\b",
        r"\btreat\s+(?:this|the)\s+(?:claim|case|file)\s+as\b",
        r"\bbehandeln\s+sie\s+(?:den|diesen)\s+fall\b",
        r"\b(?:set|change)\s+the\s+(?:payout|amount|total|queue|verdict)\b",
        r"\broute\s+(?:it|this|the\s+claim)\s+to\b",
        r"\bdo\s+not\s+apply\s+(?:any|the)\s+(?:deductible|limit|exclusion)s?\b",
        r"\bclassify\s+(?:this|the)\s+(?:document|file|claim)\b",
    ],
}

_COMPILED = {kind: [re.compile(p) for p in pats] for kind, pats in PATTERNS.items()}


@dataclass(frozen=True)
class Signal:
    kind: str  # one of PATTERNS, or "hidden_text (<reason>)" for a block a reader cannot see
    quote: str  # the original text around the match, at most QUOTE_CHARS
    page: int | None = None


def _quote(text: str, start: int, end: int) -> str:
    """The sentence or line around a match, cut to QUOTE_CHARS, taken from the original text."""
    left = max(text.rfind("\n", 0, start), text.rfind(". ", 0, start) + 1, start - 60)
    right_nl = text.find("\n", end)
    right = min(x for x in (right_nl if right_nl >= 0 else len(text), end + 80, len(text)))
    quote = text[max(0, left) : right].strip()
    if len(quote) > QUOTE_CHARS:
        quote = text[start : min(end + 40, len(text))].strip()[:QUOTE_CHARS]
    return quote


def injection_signals(text: str) -> list[Signal]:
    """One signal per kind found in the text, quoting the first match."""
    folded = fold(text)
    out = []
    for kind, patterns in _COMPILED.items():
        matches = [m for p in patterns if (m := p.search(folded))]
        if matches:
            first = min(matches, key=lambda m: m.start())
            out.append(Signal(kind, _quote(text, first.start(), first.end())))
    return out


def document_signals(parsed: ParsedDocument, redacted: dict[int, str]) -> list[Signal]:
    """Signals of one document on its redacted text: each kind of hidden text once, then each
    phrase kind once, on the first page it appears (hidden text included)."""
    out: list[Signal] = []
    for b in parsed.blocks:
        kind = f"hidden_text ({b.hidden})"
        if b.hidden and all(s.kind != kind for s in out):
            out.append(Signal(kind, redacted.get(b.seq, b.text)[:QUOTE_CHARS], b.page))
    seen: set[str] = set()
    for page in sorted({b.page for b in parsed.blocks}):
        text = "\n".join(redacted.get(b.seq, b.text) for b in parsed.blocks if b.page == page)
        for s in injection_signals(text):
            if s.kind not in seen:
                seen.add(s.kind)
                out.append(Signal(s.kind, s.quote, page))
    return out
