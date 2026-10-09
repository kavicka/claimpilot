"""Document language from stopwords and letters. Enough to pick few-shot examples and OCR hints."""

import re
from collections import Counter

STOPWORDS = {
    "de": {"und", "der", "die", "das", "mit", "für", "nicht", "datum", "rechnung", "patient", "befund", "bei", "von"},
    "it": {"il", "della", "di", "che", "per", "con", "data", "fattura", "paziente", "referto", "del", "e", "non"},
    "hr": {"i", "je", "za", "na", "se", "od", "račun", "datum", "pacijent", "broj", "nalaz", "u", "nije"},
    "en": {"the", "and", "of", "for", "with", "date", "invoice", "patient", "report", "no", "to", "was"},
    "cs": {"a", "je", "na", "se", "pro", "datum", "faktura", "pacient", "č", "zpráva", "při", "byl", "nebo"},
    "sk": {"a", "je", "na", "sa", "pre", "dátum", "číslo", "zmluvy", "poistenie", "poistený", "bol", "alebo", "som"},
}  # fmt: skip
LETTERS = {"cs": "ěřů", "sk": "äôĺľŕ", "de": "äöüß", "hr": "ćđ", "it": "àèìòù"}


def detect_language(text: str) -> str:
    words = re.findall(r"[^\W\d_]+", text.lower())
    if not words:
        return "und"
    counts = Counter(words)
    scores = {lang: sum(counts[w] for w in sw) for lang, sw in STOPWORDS.items()}
    lowered = text.lower()
    for lang, letters in LETTERS.items():
        scores[lang] += 3 * sum(lowered.count(ch) for ch in letters)
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "und"
