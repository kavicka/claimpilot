import pytest

from claimpilot_core.domain import DocType
from claimpilot_worker.ingest.doctype import classify_by_rules
from claimpilot_worker.ingest.language import detect_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Hlásenie poistnej udalosti z cestovného poistenia. Popis udalosti. Uplatňované náklady",
            DocType.CLAIM_FORM,
        ),
        (
            "Poistný certifikát – Cestovné poistenie Basic. Rozsah poistenia a limity. Poistené osoby",
            DocType.POLICY_CERTIFICATE,
        ),
        (
            "RECHNUNG Rechnung Nr. RE-2026-04417 Gesamtbetrag 279,50 EUR Behandlungsdatum",
            DocType.MEDICAL_INVOICE,
        ),
        ("Ärztlicher Befundbericht Diagnose Anamnese ICD-10 S52.5", DocType.MEDICAL_REPORT),
        (
            "Farmacia Rossi Scontrino Documento n. 1234/55555 Totale EUR 19,30 IVA inclusa",
            DocType.PHARMACY_RECEIPT,
        ),
        (
            "PROPERTY IRREGULARITY REPORT File reference VIEDN12345 Bag tag DN123456",
            DocType.PROPERTY_IRREGULARITY_REPORT,
        ),
        (
            "Verbale di denuncia Stazione Carabinieri di Rimini Oggetti sottratti",
            DocType.POLICE_REPORT,
        ),
        (
            "Potvrdenie o stornovaní zájazdu Číslo rezervácie 2026123 Stornovací poplatok",
            DocType.BOOKING_CONFIRMATION,
        ),
    ],
)
def test_rules_decide_clear_documents(text, expected):
    result = classify_by_rules(text)
    assert result is not None
    assert result.doc_type is expected
    assert result.method == "rule"


def test_rules_abstain_when_nothing_matches():
    assert classify_by_rules("<PERSON_1> 12,50 14.02.2026") is None


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Rechnung für die ambulante Untersuchung des Patienten mit Röntgen", "de"),
        ("Fattura per la visita del paziente e degli esami di laboratorio", "it"),
        ("Račun za pregled pacijenta i laboratorijske pretrage, broj računa", "hr"),
        ("Invoice for the outpatient consultation of the patient and the X-ray", "en"),
        ("Faktura za ošetření pacienta, vyšetření a léčba při úrazu", "cs"),
        ("Hlásenie poistnej udalosti, číslo zmluvy a dátum, poistený bol na dovolenke", "sk"),
    ],
)
def test_language(text, lang):
    assert detect_language(text) == lang
