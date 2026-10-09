"""Free-text parts of documents, written by a local model and cached.

Structured values never come from the model. The cache (`narratives.json`, committed) makes
`make data SEED=42` reproduce the same documents without a model; a missing entry is generated
once, or falls back to a plain template when no model is reachable.
"""

import asyncio
import hashlib
import json
from pathlib import Path

from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.llm.prompts import load_prompt
from claimpilot_datagen import catalog as cat
from claimpilot_datagen.model import DocSpec, Scenario

LANG_NAMES = {
    "de": "German",
    "it": "Italian",
    "hr": "Croatian",
    "en": "English",
    "cs": "Czech",
    "sk": "Slovak",
}

EVENT_SK = {
    "medical": "ochorel/a som počas dovolenky a musel/a som navštíviť lekára",
    "accident": "počas dovolenky som sa zranil/a",
    "luggage": "prišiel/prišla som o batožinu",
    "cancellation": "musel/a som zrušiť cestu ešte pred odchodom",
}


class Narrator:
    def __init__(self, cache_path: Path, gateway: LLMGateway | None) -> None:
        self.cache_path = cache_path
        self.cache: dict[str, str] = (
            json.loads(cache_path.read_text("utf-8")) if cache_path.exists() else {}
        )
        self.gateway = gateway
        self.loop = asyncio.new_event_loop()
        self.used: set[str] = set()
        self.generated = 0
        self.fallbacks = 0

    def save(self, *, prune: bool = True) -> None:
        """Write the cache; with `prune`, keep only entries this run used, so the committed file
        matches the dataset exactly."""
        keep = {k: v for k, v in self.cache.items() if not prune or k in self.used}
        self.cache_path.write_text(
            json.dumps(dict(sorted(keep.items())), ensure_ascii=False, indent=1) + "\n", "utf-8"
        )

    def _text(self, prompt_id: str, variables: dict[str, str], fallback: str) -> str:
        prompt = load_prompt(prompt_id)
        key = hashlib.sha256(
            json.dumps([prompt.sha, variables], ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:24]
        self.used.add(key)
        if key in self.cache:
            return self.cache[key]
        text = None
        if self.gateway is not None:
            try:
                gen = self.loop.run_until_complete(
                    self.gateway.generate_text("narrative", prompt_id, variables)
                )
                text = " ".join(gen.value.split())
            except Exception:
                text = None
        if not text:
            self.fallbacks += 1
            return fallback
        self.generated += 1
        self.cache[key] = text
        return text

    def claim_description(self, s: Scenario, d: DocSpec) -> str:
        facts = [
            f"Druh udalosti: {s.claim_type.value}",
            f"Miesto: {s.city}, {s.destination.name_sk}",
        ]
        dx = s.facts.get("diagnosis")
        if dx:
            facts.append(f"Zdravotný problém: {cat.DIAGNOSES[dx]['sk']}")
        if s.facts.get("activity") == "paragliding":
            facts.append("Úraz sa stal pri tandemovom lete na paraglide.")
        elif s.facts.get("activity") == "skiing":
            facts.append("Úraz sa stal pri lyžovaní na zjazdovke.")
        if "delay_hours" in s.facts:
            facts.append(
                f"Batožina prišla s oneskorením asi {s.facts['delay_hours']} hodín, musel/a som si kúpiť hygienu a oblečenie."
            )
        if "theft_place" in s.facts:
            facts.append(
                f"Veci mi ukradli, miesto krádeže: {s.facts['theft_place']}. Krádež som nahlásil/a na polícii."
            )
        if (
            s.claim_type.value == "luggage"
            and "theft_place" not in s.facts
            and "delay_hours" not in s.facts
        ):
            facts.append("Letecká spoločnosť batožinu stratila, na letisku som spísal/a záznam.")
        if s.claim_type.value == "cancellation":
            facts.append(
                "Pred odchodom som ochorel/a, lekár mi cestovanie neodporučil, cestu som stornoval/a v cestovnej kancelárii."
            )
        fallback = f"Počas cesty ({s.city}) {EVENT_SK[s.claim_type.value]}. Prikladám doklady."
        return self._text("narrative/claim_description", {"facts": "\n".join(facts)}, fallback)

    def medical_treatment(self, s: Scenario, d: DocSpec) -> str:
        dx = cat.DIAGNOSES[d.data["diagnosis"]]
        hospital = d.data.get("discharge_date") is not None
        facts = f"Diagnosis: {dx['en']} ({d.data['diagnosis']}). {'Inpatient stay.' if hospital else 'Outpatient visit.'}"
        if dx["kind"] == "fracture":
            facts += " Imaging confirms the fracture."
        elif dx["kind"] == "injury":
            facts += " Imaging shows no fracture."
        fallback = {
            "de": "Klinische Untersuchung durchgeführt. Befund entsprechend der Diagnose. Therapie eingeleitet, Kontrolle beim Hausarzt empfohlen.",
            "it": "Eseguita visita clinica. Quadro compatibile con la diagnosi. Terapia impostata, controllo dal medico curante.",
            "hr": "Učinjen klinički pregled. Nalaz odgovara dijagnozi. Započeta terapija, kontrola kod liječnika obiteljske medicine.",
            "cs": "Provedeno klinické vyšetření. Nález odpovídá diagnóze. Zahájena léčba, kontrola u praktického lékaře.",
            "sk": "Vykonané klinické vyšetrenie. Nález zodpovedá diagnóze. Nasadená liečba, cestovanie neodporúčané.",
        }.get(
            d.language,
            "Clinical examination performed. Findings consistent with the diagnosis. Treatment started, follow-up with the family doctor advised.",
        )
        return self._text(
            "narrative/medical_treatment",
            {"language": LANG_NAMES[d.language], "facts": facts},
            fallback,
        )

    def police_description(self, s: Scenario, d: DocSpec) -> str:
        where = (
            "from a locked car parked near the beach"
            if d.data["unattended"]
            else "from a beach bag while the complainant was swimming"
        )
        facts = f"Theft in {s.city} {where}. Items: {', '.join(x[0] for x in d.data['stolen'])}."
        fallback = f"The complainant reports a theft in {s.city} {where}."
        return self._text(
            "narrative/police_description",
            {"language": LANG_NAMES[d.language], "facts": facts},
            fallback,
        )
