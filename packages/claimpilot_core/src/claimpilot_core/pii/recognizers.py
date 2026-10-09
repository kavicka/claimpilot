"""Presidio pattern recognizers for Slovak and Czech identifiers, with checksum validation.

Each recognizer finds candidates by regex and keeps only values that validate (rodné číslo mod 11,
IBAN mod 97) or that sit next to a context word (ID card numbers), so invoice numbers and bag tags
are not redacted by accident.
"""

import re

from presidio_analyzer import Pattern, PatternRecognizer, RecognizerResult
from presidio_analyzer.predefined_recognizers import EmailRecognizer

from claimpilot_core.identifiers import is_valid_iban, parse_rodne_cislo

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

    # Countries whose IBAN is all digits after the country code, so OCR letter/digit mix-ups can be
    # undone before the checksum: "SKO3 6500..." (letter O) is "SK03 6500...".
    NUMERIC_BBAN = frozenset({"SK", "CZ", "AT", "DE", "HR", "HU", "PL", "SI", "TR"})

    @classmethod
    def repair_ocr(cls, text: str) -> str:
        compact = text.replace(" ", "")
        if compact[:2] not in cls.NUMERIC_BBAN:
            return compact
        return compact[:2] + compact[2:].translate(str.maketrans("OoIlSB", "001158"))

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


def pattern_recognizers() -> list[PatternRecognizer]:
    email = EmailRecognizer(supported_language="any")
    return [
        RodneCisloRecognizer(),
        IbanRecognizerSk(),
        PhoneRecognizerIntl(),
        IdCardRecognizer(),
        LicencePlateRecognizer(),
        AddressRecognizer(),
        email,
    ]


def run_patterns(text: str) -> list[RecognizerResult]:
    out: list[RecognizerResult] = []
    for rec in pattern_recognizers():
        out.extend(rec.analyze(text, rec.supported_entities, None))
    return out
