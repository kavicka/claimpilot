import re

import pytest
from cryptography.fernet import Fernet

from claimpilot_core.logging import redact_vault_values, register_secret
from claimpilot_core.pii.guard import ClaimRedactor, Span, fold, pattern_spans, rehydrate
from claimpilot_core.pii.vault import Vault, VaultKeyMissingError


def entities(text):
    return {(s.entity, s.text) for s in pattern_spans(text)}


def test_birth_number_with_valid_checksum_is_found():
    assert ("BIRTH_NUMBER", "905605/0003") in entities("Rodné číslo 905605/0003, nar. 1990")


def test_birth_number_with_bad_checksum_is_ignored():
    assert not any(e == "BIRTH_NUMBER" for e, _ in entities("Rodné číslo 905605/0004"))


def test_iban_with_spaces_is_found_and_validated():
    text = "IBAN: SK31 1200 0000 1987 4263 7541 na výplatu"
    assert ("IBAN", "SK31 1200 0000 1987 4263 7541") in entities(text)
    assert not any(e == "IBAN" for e, _ in entities("IBAN: SK31 1200 0000 1987 4263 7542"))


def test_invoice_and_policy_numbers_are_not_pii():
    found = entities("Rechnung Nr. RE-2026-04417, Poistná zmluva CP58181396, Fattura FT-2026-05207")
    assert found == set()


def test_id_card_needs_a_context_word():
    assert ("ID_CARD", "EA123456") in entities("Ausweis: EA123456")
    assert not any(e == "ID_CARD" for e, _ in entities("Bag tag DN123456"))


def test_phone_and_email():
    found = entities("Telefón +421 915 123 456, e-mail jana.kovacova12@posta.example.sk")
    assert ("PHONE", "+421 915 123 456") in found
    assert ("EMAIL_ADDRESS", "jana.kovacova12@posta.example.sk") in found


def test_street_before_postcode_is_an_address():
    assert ("ADDRESS", "Brnianska 25") in entities("Adresa Brnianska 25, 918 48 Vrútky")


def test_slovak_licence_plate():
    assert ("LICENCE_PLATE", "BA123XY") in entities("Kfz-Kennzeichen BA123XY")


def fake_ner(names):
    def ner(text):
        out = []
        for name in names:
            for m in re.finditer(re.escape(name), text):
                out.append(Span(m.start(), m.end(), "PERSON", name, 0.99, "ner"))
        return out

    return ner


def test_tokens_are_consistent_across_documents_and_variants():
    r = ClaimRedactor(ner=fake_ner(["Jana Kováčová", "Nina Milanesi"]))
    form = "Meno a priezvisko Jana Kováčová, IBAN SK31 1200 0000 1987 4263 7541"
    report = "Paziente: Jana Kováčová. Medico: Nina Milanesi"
    pir = "Passenger name KOVACOVA/JANA MS, account SK3112000000198742637541"
    ocr = "Patient: Jana Kovacova"  # OCR lost the diacritics
    r.observe([form, report, pir, ocr])
    assert r.redact(form) == "Meno a priezvisko <PERSON_1>, IBAN <IBAN_1>"
    assert r.redact(report) == "Paziente: <PERSON_1>. Medico: <PERSON_2>"
    assert r.redact(pir) == "Passenger name <PERSON_1> MS, account <IBAN_1>"
    assert r.redact(ocr) == "Patient: <PERSON_1>"


def test_a_name_missed_on_one_page_is_caught_from_another():
    r = ClaimRedactor(ner=fake_ner(["Bruno Paška"]))
    r.observe(["Poistený: Bruno Paška"])
    assert r.redact("Rechnung für Bruno Paška") == "Rechnung für <PERSON_1>"


def test_rehydrate_round_trip():
    r = ClaimRedactor(ner=fake_ner(["Bruno Paška"]))
    text = "Patient Bruno Paška, RČ 905605/0003"
    r.observe([text])
    red = r.redact(text)
    assert "Paška" not in red and "905605" not in red
    values = {t: v for t, (_, v) in r.mapping().items()}
    assert rehydrate(red, values) == text


def test_fold_keeps_length():
    s = "Kováčová Ľubomír Śląsk ß"
    assert len(fold(s)) == len(s)
    assert fold("Kováčová") == "kovacova"


def test_registered_secrets_are_scrubbed_from_logs():
    register_secret("Zuzana Testovacia")
    out = redact_vault_values(None, "info", {"event": "x", "who": "client Zuzana Testovacia"})
    assert out["who"] == "client [REDACTED]"


def test_vault_round_trip_and_missing_key():
    v = Vault(Fernet.generate_key().decode())
    blob = v.encrypt("905605/0003")
    assert b"905605" not in blob
    assert v.decrypt(blob) == "905605/0003"
    with pytest.raises(VaultKeyMissingError):
        Vault("")


def test_doctor_name_after_a_label_is_redacted_without_the_signature_words():
    from claimpilot_core.pii.recognizers import LabeledNameRecognizer

    text = "Behandelnde/r Ärztin/Arzt: Rouven Vollbrecht Unterschrift, Stempel"
    found = [text[r.start : r.end] for r in LabeledNameRecognizer().analyze(text, ["PERSON"])]
    assert found == ["Rouven Vollbrecht"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Kováčová, Jana", "<PERSON_1>"),  # surname first, with a comma
        ("J. Kováčová", "<PERSON_1>"),  # initial
        ("Jana\nKováčová", "<PERSON_1>"),  # broken across lines by OCR
        ("JANA KOVÁČOVÁ", "<PERSON_1>"),
        ("Kovacova Jana", "<PERSON_1>"),  # no diacritics, reversed
        ("Ošetrenie pacientky Jany Kováčovej", "Ošetrenie pacientky <PERSON_1>"),  # genitive
        ("pre Janu Kováčovú", "pre <PERSON_1>"),  # accusative
        ("Vážená pani Kováčová,", "Vážená pani <PERSON_1>,"),  # surname after a form of address
        ("s pánom Petrom Novákom", "s pánom <PERSON_2>"),  # instrumental, male
        ("Petra Nováka", "<PERSON_2>"),  # fleeting e: Peter -> Petra
        ("Herr Novák", "Herr <PERSON_2>"),
    ],
)
def test_a_known_name_is_found_in_other_forms(text, expected):
    r = ClaimRedactor(ner=fake_ner(["Jana Kováčová", "Peter Novák"]))
    r.observe(["Poistená Jana Kováčová, lekár Peter Novák"])
    assert r.redact(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "nová liečba",  # an ordinary word that shares a stem with a name
        "Kováčovská ulica",
        "Peter",  # a first name alone is not enough
        "Novákovci",
    ],
)
def test_name_forms_do_not_swallow_ordinary_words(text):
    r = ClaimRedactor(ner=fake_ner(["Jana Kováčová", "Peter Novák"]))
    r.observe(["Poistená Jana Kováčová, lekár Peter Novák"])
    assert r.redact(text) == text
