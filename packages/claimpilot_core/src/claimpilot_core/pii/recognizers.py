"""Presidio pattern recognizers for Slovak and Czech identifiers, with checksum validation.

Each recognizer finds candidates by regex and keeps only values that validate (rodné číslo mod 11,
IBAN mod 97) or that sit next to a context word (ID card numbers), so invoice numbers and bag tags
are not redacted by accident.
"""

import re

from presidio_analyzer import Pattern, PatternRecognizer, RecognizerResult
from presidio_analyzer.predefined_recognizers import EmailRecognizer

from claimpilot_core.identifiers import is_valid_iban, parse_rodne_cislo, repair_iban_ocr

# Presidio defaults to IGNORECASE; identifiers here are case-sensitive (an IBAN must not swallow
# the lowercase word after it).
CASE_SENSITIVE = re.DOTALL | re.MULTILINE


class RodneCisloRecognizer(PatternRecognizer):
    def __init__(self) -> None:
        super().__init__(
            supported_entity="BIRTH_NUMBER",
            patterns=[
                Pattern("rc_slash", r"\b\d{6}\s?/\s?\d{3,4}\b", 0.6),
                Pattern("rc_plain", r"\b\d{10}\b", 0.3),
            ],
            context=["rodné", "rodne", "číslo", "rč", "birth number"],
            supported_language="any",
        )

    def validate_result(self, pattern_text: str) -> bool:
        return parse_rodne_cislo(pattern_text.replace(" ", "")) is not None


class IbanRecognizerSk(PatternRecognizer):
    def __init__(self) -> None:
        super().__init__(
            supported_entity="IBAN",
            patterns=[
                Pattern(
                    "iban",
                    r"\b[A-Z]{2}[0-9OIl]{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b",
                    0.6,
                )
            ],
            supported_language="any",
            global_regex_flags=CASE_SENSITIVE,
        )

    @staticmethod
    def repair_ocr(text: str) -> str:
        return repair_iban_ocr(text)

    def validate_result(self, pattern_text: str) -> bool:
        return is_valid_iban(pattern_text) or is_valid_iban(self.repair_ocr(pattern_text))


class PhoneRecognizerIntl(PatternRecognizer):
    def __init__(self) -> None:
        super().__init__(
            supported_entity="PHONE",
            patterns=[
                Pattern("intl", r"\+\d{2,3}(?:[ ]?\d{2,4}){2,5}\b", 0.7),
                Pattern("sk_mobile", r"\b09\d{2}[ ]?\d{3}[ ]?\d{3}\b", 0.6),
            ],
            supported_language="any",
        )


class IdCardRecognizer(PatternRecognizer):
    """Slovak ID card numbers (two letters, six digits). Bag tags share the shape, so a context
    word must appear shortly before the value."""

    CONTEXT = re.compile(
        r"(op|občiansk|obciansk|ausweis|documento|isprava|doklad|id document|id card|passport|pas)\W{0,20}$",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(
            supported_entity="ID_CARD",
            patterns=[Pattern("sk_id", r"\b[A-Z]{2}\d{6}\b", 0.5)],
            supported_language="any",
            global_regex_flags=CASE_SENSITIVE,
        )

    def analyze(self, text, entities, nlp_artifacts=None, regex_flags=None):
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        return [r for r in results if self.CONTEXT.search(text[max(0, r.start - 40) : r.start])]


class LicencePlateRecognizer(PatternRecognizer):
    DISTRICTS = "BA|BB|BL|BR|BS|BJ|BN|BY|CA|DK|DS|DT|GA|GL|HC|HE|IL|KA|KE|KK|KM|KN|KS|LC|LE|LM|LV|MA|MI|ML|MT|MY|NI|NM|NO|NR|NZ|PB|PD|PE|PK|PN|PO|PP|PT|PU|RA|RK|RS|RV|SA|SB|SC|SE|SI|SK|SL|SN|SO|SP|SV|TN|TO|TR|TS|TT|TV|VK|VT|ZA|ZC|ZH|ZM|ZV"

    def __init__(self) -> None:
        super().__init__(
            supported_entity="LICENCE_PLATE",
            patterns=[
                Pattern("sk_plate", rf"\b(?:{self.DISTRICTS})[- ]?\d{{3}}[- ]?[A-Z]{{2}}\b", 0.6)
            ],
            supported_language="any",
            global_regex_flags=CASE_SENSITIVE,
        )


class AddressRecognizer(PatternRecognizer):
    """A street with a house number followed by a Slovak or Czech postcode and town; the street part
    is the entity (it is what identifies the person; the town alone does not)."""

    STREET = r"[A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽ][\wáäčďéíĺľňóôŕšťúýžě\.\-]*(?:\s[\wÁ-žáäčďéíĺľňóôŕšťúýžě\.\-]+){0,3}\s\d{1,4}(?:/\d{1,4})?[a-zA-Z]?"

    def __init__(self) -> None:
        super().__init__(
            supported_entity="ADDRESS",
            patterns=[
                Pattern("street_postcode", rf"{self.STREET}(?=,\s?\d{{3}}\s?\d{{2}}\s)", 0.6)
            ],
            supported_language="any",
            global_regex_flags=CASE_SENSITIVE,
        )

    LABELS = re.compile(
        r"^(?:(?:adresa|address|wohnadresse|bydliště|bydlisko|residenza|home|permanent|trvalé|bydlisko)\s*:?\s+)+",
        re.IGNORECASE,
    )

    def analyze(self, text, entities, nlp_artifacts=None, regex_flags=None):
        out = []
        for r in super().analyze(text, entities, nlp_artifacts, regex_flags):
            m = self.LABELS.match(text[r.start : r.end])
            if m:
                r.start += m.end()
            if r.end - r.start >= 4:
                out.append(r)
        return out


class LabeledNameRecognizer(PatternRecognizer):
    """A person's name right after a form label (doctor, patient) in the six document languages.
    The NER model misses some of these, e.g. a German doctor's name in a signature line."""

    LABEL = (
        r"(?i:arzt|ärztin|lekár|lékař|medico(?:\s+curante)?|liječnik|lijecnik|physician|doctor"
        r"|pacient|patient|paziente|pacijent)"
    )
    WORD = r"[A-ZÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽÖÜĆĐ][a-zäöüßáčďéíĺľňóôŕšťúýžěćđ'\-]+"
    PATTERN = re.compile(rf"{LABEL}\s*:\s*(?:(?:MUDr|Dr|Dott)\.\s*)?({WORD}(?:\s{WORD}){{1,2}})")

    def __init__(self) -> None:
        super().__init__(
            supported_entity="PERSON",
            patterns=[Pattern("labeled_name", r"(?!x)x", 0.0)],  # matching happens in analyze
            supported_language="any",
        )

    # Form words that follow the name on a signature line
    STOP = frozenset(
        {
            "unterschrift",
            "stempel",
            "podpis",
            "pečiatka",
            "razítko",
            "firma",
            "timbro",
            "potpis",
            "pečat",
            "signature",
            "stamp",
            "datum",
            "dátum",
            "date",
            "data",
        }
    )

    def analyze(self, text, entities, nlp_artifacts=None, regex_flags=None):
        out = []
        for m in self.PATTERN.finditer(text):
            words = m.group(1).split(" ")
            while words and words[-1].lower() in self.STOP:
                words.pop()
            if len(words) >= 2:
                start = m.start(1)
                out.append(RecognizerResult("PERSON", start, start + len(" ".join(words)), 0.7))
        return out


class BirthDateRecognizer(PatternRecognizer):
    """A date of birth after its label in the claim languages ("geb. 01.11.1988", "nar. 1. 11. 1988",
    "DOB: 01 Nov 1988", "nato/a il 01/11/1988"). Other dates (visits, invoices, the event) are
    needed for the decision and stay. When OCR puts the label and the date in separate blocks,
    ClaimRedactor.observe pairs them (LABEL_AT_END, DATE_ANYWHERE)."""

    LABEL = (
        r"(?:geb\.|geboren(?:\s+am)?|geburtsdatum|nar\.|narodená|narodený|narozen[aá]?"
        r"|dátum\s+narodenia|datum\s+narození|date\s+of\s+birth|d\.o\.b\.|dob|born(?:\s+on)?"
        r"|nato/a\s+il|nat[oa]\s+il|data\s+di\s+nascita|rođen/a|rođen[a]?|datum\s+rođenja"
        r"|data\s+urodzenia|ur\.|doğum\s+tarihi)"
    )
    DATE = (
        r"(?:\d{1,2}\.\s?\d{1,2}\.\s?\d{4}\.?|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}"
        r"|\d{1,2}\s[A-Za-z]{3,9}\.?\s\d{4})"
    )
    PATTERN = re.compile(rf"(?<![\w]){LABEL}\s*[:|,]?\s*({DATE})", re.IGNORECASE)
    LABEL_AT_END = re.compile(rf"(?<![\w]){LABEL}\s*:?\s*$", re.IGNORECASE)
    DATE_ANYWHERE = re.compile(rf"(?<![\w])({DATE})(?![\w])")

    def __init__(self) -> None:
        super().__init__(
            supported_entity="BIRTH_DATE",
            patterns=[Pattern("birth_date", r"(?!x)x", 0.0)],  # matching happens in analyze
            supported_language="any",
        )

    def analyze(self, text, entities, nlp_artifacts=None, regex_flags=None):
        return [
            RecognizerResult("BIRTH_DATE", m.start(1), m.end(1), 0.85)
            for m in self.PATTERN.finditer(text)
        ]


def pattern_recognizers() -> list[PatternRecognizer]:
    email = EmailRecognizer(supported_language="any")
    return [
        RodneCisloRecognizer(),
        IbanRecognizerSk(),
        PhoneRecognizerIntl(),
        IdCardRecognizer(),
        LicencePlateRecognizer(),
        AddressRecognizer(),
        LabeledNameRecognizer(),
        BirthDateRecognizer(),
        email,
    ]


def run_patterns(text: str) -> list[RecognizerResult]:
    out: list[RecognizerResult] = []
    for rec in pattern_recognizers():
        out.extend(rec.analyze(text, rec.supported_entities, None))
    return out
