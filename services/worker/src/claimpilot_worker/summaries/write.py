"""Texts from structured facts: handler summary (SK), client letter (formal SK), group summary (DE).

The model sees a JSON of the decision, never the documents, and every text passes the
fact-consistency check before it is stored. The letter is a fixed template; the model writes only
the reasons paragraph.
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_worker.summaries.factcheck import Facts, Violation, check

MONTHS_SK = [
    "januára",
    "februára",
    "marca",
    "apríla",
    "mája",
    "júna",
    "júla",
    "augusta",
    "septembra",
    "októbra",
    "novembra",
    "decembra",
]


def sk_amount(value: Decimal) -> str:
    whole, frac = f"{value:.2f}".split(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return f"{' '.join(groups)},{frac}"


def sk_date(d: date) -> str:
    return f"{d.day}. {d.month}. {d.year}"


def clause_sk(clause_id: str) -> str:
    a, p = clause_id[1:].split(".")
    return f"čl. {a} ods. {p}"


@dataclass
class DecisionFacts:
    reference: str
    product: str
    claim_type: str
    event_date: date | None
    queue: str | None
    items: list[dict[str, Any]]  # description, amount, currency, verdict, clauses, payout
    total_payout: Decimal
    deductible: Decimal
    red_flags: list[str]
    missing: list[str]
    insured_token: str

    def claimed_by_currency(self) -> dict[str, Decimal]:
        """Totals the writer would otherwise add up itself (and get wrong)."""
        out: dict[str, Decimal] = {}
        for i in self.items:
            if i["amount"] is not None and i["currency"]:
                out[i["currency"]] = out.get(i["currency"], Decimal(0)) + i["amount"]
        return out

    def as_prompt_json(self) -> str:
        return json.dumps(
            {
                "referencia": self.reference,
                "produkt": self.product,
                "druh_udalosti": self.claim_type,
                "datum_udalosti": sk_date(self.event_date) if self.event_date else None,
                "front": self.queue,
                "polozky": [
                    {
                        "popis": i["description"],
                        "uplatnena_suma": f"{sk_amount(i['amount'])} {i['currency']}"
                        if i["amount"] is not None and i["currency"]
                        else "suma alebo mena na doklade je nečitateľná",
                        "rozhodnutie": i["verdict"],
                        "clanky_vpp": [clause_sk(c) for c in i["clauses"]],
                        "plnenie_eur": sk_amount(i["payout"]),
                    }
                    for i in self.items
                ],
                "uplatnene_spolu": [
                    f"{sk_amount(v)} {c}" for c, v in sorted(self.claimed_by_currency().items())
                ],
                "plnenie_spolu_eur": sk_amount(self.total_payout),
                "spoluucast_eur": sk_amount(self.deductible),
                "rizikove_signaly": self.red_flags,
                "chybajuce_informacie": self.missing,
                "poisteny": self.insured_token,
            },
            ensure_ascii=False,
            indent=1,
        )

    def check_facts(self) -> Facts:
        amounts = {self.total_payout, self.deductible}
        for i in self.items:
            amounts |= {a for a in (i["amount"], i["payout"]) if a is not None}
        amounts |= set(self.claimed_by_currency().values())
        clauses = {c for i in self.items for c in i["clauses"]}
        return Facts(
            amounts=amounts, dates={self.event_date} if self.event_date else set(), clauses=clauses
        )


@dataclass
class Text:
    kind: str
    language: str
    text: str
    violations: list[Violation]
    prompt_tag: str | None


def letter(facts: DecisionFacts, reasons: str) -> str:
    if facts.total_payout > 0:
        decision = (
            f"po posúdení Vašej poistnej udalosti {facts.reference} Vám poisťovňa vyplatí "
            f"poistné plnenie {sk_amount(facts.total_payout)} EUR na účet uvedený v hlásení."
        )
    else:
        decision = (
            f"po posúdení Vašej poistnej udalosti {facts.reference} poisťovňa poistné plnenie "
            "neposkytne."
        )
    return "\n\n".join(
        [
            "Vážená pani / Vážený pán,",
            decision,
            f"Odôvodnenie\n{reasons.strip()}",
            "Ak s rozhodnutím nesúhlasíte, môžete do 30 dní podať námietku. Uveďte číslo "
            "poistnej udalosti a priložte doklady, ktoré rozhodnutie môžu zmeniť.",
            "S pozdravom\nOddelenie likvidácie poistných udalostí\nVzorová poisťovňa, a. s.",
        ]
    )


async def write_all(facts: DecisionFacts, gateway: LLMGateway) -> list[Text]:
    variables = {"facts": facts.as_prompt_json()}
    check_facts = facts.check_facts()
    out = []
    handler = await gateway.generate_text("summaries", "summaries/handler_sk", variables)
    out.append(
        Text("handler", "sk", handler.value, check(handler.value, check_facts), handler.prompt_tag)
    )
    reasons = await gateway.generate_text("summaries", "summaries/letter_reasons_sk", variables)
    body = letter(facts, reasons.value)
    out.append(Text("client_letter", "sk", body, check(body, check_facts), reasons.prompt_tag))
    group = await gateway.generate_text("summaries", "summaries/group_de", variables)
    out.append(Text("group", "de", group.value, check(group.value, check_facts), group.prompt_tag))
    return out
