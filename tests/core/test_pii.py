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


@pytest.mark.parametrize(
    "text",
    [
        "Patient/in Jana Kováčová, geb. 01.11.1988",
        "Fridrich Kubička, nar. 1. 11. 1988",
        "Date of birth: 01/11/1988",
        "DOB 01 Nov 1988",
        "Mario Rossi, nato/a il 01/11/1988",
        "Datum rođenja: 01.11.1988.",
        "GEB. | 01.11.1988",
    ],
)
def test_a_date_of_birth_after_its_label_is_personal_data(text):
    r = ClaimRedactor(ner=None)
    r.observe([text])
    assert "<DOB_1>" in r.redact(text)
    assert "1988" not in r.redact(text)


def test_a_birth_date_in_its_own_block_after_the_label_block_is_found():
    """Docling reads a form cell as two blocks: 'GEB.' and then '01.11.1988'."""
    r = ClaimRedactor(ner=None)
    r.observe(["PATIENT/IN", "<PERSON_1>", "UNTERSUCHUNG", "03.06.2026", "GEB.", "01.11.1988"])
    assert r.redact("01.11.1988") == "<DOB_1>"
    assert r.redact("03.06.2026") == "03.06.2026"  # the visit date is not personal


def test_the_same_birth_date_is_one_token_in_every_printed_form():
    r = ClaimRedactor(ner=None)
    r.observe(["Ärztlicher Befundbericht, geb. 01.11.1988"])
    assert r.redact("Pacijent Jana, rođena 1. 11. 1988") == "Pacijent Jana, rođena <DOB_1>"
    assert r.redact("born on 1988-11-01") == "born on <DOB_1>"
    assert r.redact("DOB 01 NOV 1988") == "DOB <DOB_1>"


def test_dates_without_a_birth_label_stay():
    r = ClaimRedactor(ner=None)
    text = "Datum: 16.06.2026, Untersuchung 03.06.2026, Rechnung vom 1. 7. 2026"
    r.observe([text])
    assert r.redact(text) == text


def test_a_tokenized_date_is_stored_as_the_token():
    from claimpilot_core.fields import normalize

    assert normalize("patient_birth_date", "<DOB_1>") == "<DOB_1>"
    assert normalize("visit_date", "03.06.2026") == "2026-06-03"


def test_a_label_glued_to_the_block_before_still_marks_the_date():
    r = ClaimRedactor(ner=None)
    r.observe(
        ["Podpis, pečiatka NAR.", "23. 2. 1969", "PACIENT Zoja | NAR.", "Nižnánská | 29. 3. 1996"]
    )
    assert r.redact("23. 2. 1969") == "<DOB_1>"
    assert r.redact("Nižnánská | 29. 3. 1996") == "Nižnánská | <DOB_2>"


def test_the_birth_number_gives_the_date_of_birth_wherever_it_is_printed():
    """905605/0003: a woman born 5 June 1990 (month + 50)."""
    r = ClaimRedactor(ner=None)
    r.observe(["Rodné číslo 905605/0003", "Ospedale Civile: 05/06/1990"])
    assert r.redact("Ospedale Civile: 05/06/1990") == "Ospedale Civile: <DOB_1>"
    assert r.redact("rođena 5. 6. 1990.") == "rođena <DOB_1>."


@pytest.mark.parametrize(
    "text", ["DIČ: 2155120011", "DIČ 2993547293", "IČ DPH: 2155120011", "VAT ID: 2155120011"]
)
def test_a_tax_number_after_its_label_is_not_a_birth_number(text):
    # Both validate as a rodné číslo (mod 11, a plausible date); the label says they are tax ids.
    assert not any(e == "BIRTH_NUMBER" for e, _ in entities(text))


def test_a_birth_number_after_its_own_label_is_still_found():
    assert ("BIRTH_NUMBER", "2155120011") in entities("RČ: 2155120011, DIČ: 2997673481")
