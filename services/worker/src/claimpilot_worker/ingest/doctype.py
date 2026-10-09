"""Document type: keyword rules first, a small model with a fixed label set only when rules tie.

Runs on redacted text (the model call may leave the machine in Phase 2).
"""

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from claimpilot_core.domain import DocType
from claimpilot_core.llm.gateway import LLMGateway

# Phrases per type, all languages the dataset uses. Weight 3 = decisive title, 1 = supporting word.
KEYWORDS: dict[DocType, list[tuple[str, int]]] = {
    DocType.CLAIM_FORM: [("hlásenie poistnej udalosti", 3), ("uplatňované náklady", 3), ("popis udalosti", 2), ("druh udalosti", 2), ("iban na výplatu", 1)],
    DocType.POLICY_CERTIFICATE: [("poistný certifikát", 3), ("rozsah poistenia", 2), ("poistené osoby", 2), ("začiatok poistenia", 1), ("limit poistného plnenia", 1)],
    DocType.MEDICAL_REPORT: [("befundbericht", 3), ("referto medico", 3), ("medicinsko izvješće", 3), ("medical report", 3), ("lékařská zpráva", 3), ("lekárska správa", 3), ("anamnes", 2), ("anamnez", 2), ("history", 1), ("diagnos", 1), ("dijagnoz", 1), ("icd-10", 1), ("mkb-10", 1), ("mkn-10", 1), ("mkch-10", 1)],
    DocType.MEDICAL_INVOICE: [("rechnung nr", 3), ("fattura n", 3), ("račun br", 3), ("invoice no", 3), ("faktura č", 3), ("gesamtbetrag", 2), ("totale da pagare", 2), ("ukupno za platiti", 2), ("total due", 2), ("celkem k úhradě", 2), ("behandlungsdatum", 1), ("data prestazione", 1), ("datum usluge", 1), ("date of service", 1), ("datum ošetření", 1)],
    DocType.PHARMACY_RECEIPT: [("kassenbon", 3), ("scontrino", 3), ("pokladní doklad", 3), ("receipt no", 3), ("broj računa", 3), ("apotheke", 2), ("farmacia", 2), ("ljekarna", 2), ("pharmacy", 2), ("lékárna", 2), ("drogerie", 2), ("drogerija", 2), ("mini market", 2), ("market", 1), ("mwst", 1), ("iva inclusa", 1), ("pdv", 1), ("vat included", 1), ("dph", 1)],
    DocType.PROPERTY_IRREGULARITY_REPORT: [("property irregularity report", 3), ("bag tag", 2), ("file reference", 2), ("baggage services", 2), ("bag status", 1)],
    DocType.POLICE_REPORT: [("niederschrift über eine anzeige", 3), ("verbale di denuncia", 3), ("zapisnik o prijavi", 3), ("theft report", 3), ("úřední záznam", 3), ("polizei", 2), ("carabinieri", 2), ("policij", 2), ("police", 2), ("policie", 2), ("gestohlene", 1), ("oggetti sottratti", 1), ("otuđeni", 1), ("stolen property", 1), ("odcizené", 1)],
    DocType.BOOKING_CONFIRMATION: [("potvrdenie o stornovaní", 3), ("cancellation confirmation", 3), ("číslo rezervácie", 2), ("booking number", 2), ("stornovací poplatok", 2), ("cancellation fee", 2), ("cestovná kancelária", 1), ("ck ", 1)],
}  # fmt: skip

MIN_SCORE = 3
MIN_MARGIN = 2


@dataclass
class DocTypeResult:
    doc_type: DocType
    confidence: float
    method: str  # rule | llm
    scores: dict[str, int]


def rule_scores(text: str) -> dict[DocType, int]:
    low = re.sub(r"\s+", " ", text.lower())
    return {t: sum(w for kw, w in kws if kw in low) for t, kws in KEYWORDS.items()}


def classify_by_rules(text: str) -> DocTypeResult | None:
    scores = rule_scores(text)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (top, s1), (_, s2) = ranked[0], ranked[1]
    if s1 >= MIN_SCORE and s1 - s2 >= MIN_MARGIN:
        conf = min(0.99, 0.6 + 0.08 * (s1 - s2))
        return DocTypeResult(top, conf, "rule", {k.value: v for k, v in scores.items()})
    return None


class DocTypeAnswer(BaseModel):
    doc_type: DocType = Field(description="The type of this document")


async def classify(text: str, gateway: LLMGateway, *, max_chars: int = 2500) -> DocTypeResult:
    by_rules = classify_by_rules(text)
    if by_rules is not None:
        return by_rules
    scores = {k.value: v for k, v in rule_scores(text).items()}
    gen = await gateway.generate_json(
        "doc_type", "doc_type/classify", DocTypeAnswer, {"text": text[:max_chars]}
    )
    return DocTypeResult(gen.value.doc_type, 0.7, "llm", scores)
