"""Scenario data model: everything the generator decides before it renders a single page."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from claimpilot_core.domain import (
    ClaimStatus,
    ClaimType,
    Coverage,
    CoverageVerdict,
    DocType,
    Product,
)
from claimpilot_core.domain import Queue as QueueName


@dataclass(frozen=True)
class Destination:
    code: str
    name_sk: str
    doc_lang: str  # language of local documents
    locale: str  # number and date format of local documents
    currency: str
    cities: tuple[str, ...]
    faker_locale: str
    airport: str


DESTINATIONS: dict[str, Destination] = {
    d.code: d
    for d in [
        Destination("AT", "Rakúsko", "de", "de", "EUR", ("Kitzbühel", "Innsbruck", "Salzburg", "Schladming", "Wien"), "de_AT", "VIE"),
        Destination("DE", "Nemecko", "de", "de", "EUR", ("München", "Garmisch-Partenkirchen", "Berlin", "Hamburg"), "de_DE", "MUC"),
        Destination("CH", "Švajčiarsko", "de", "de-ch", "CHF", ("Zermatt", "Davos", "Luzern"), "de_CH", "ZRH"),
        Destination("IT", "Taliansko", "it", "it", "EUR", ("Rimini", "Bibione", "Livigno", "Roma", "Lignano Sabbiadoro"), "it_IT", "FCO"),
        Destination("HR", "Chorvátsko", "hr", "hr", "EUR", ("Split", "Makarska", "Zadar", "Dubrovnik", "Poreč"), "hr_HR", "SPU"),
        Destination("ES", "Španielsko", "en", "en", "EUR", ("Barcelona", "Málaga", "Palma de Mallorca"), "es_ES", "BCN"),
        Destination("GR", "Grécko", "en", "en", "EUR", ("Chania", "Rodos", "Thessaloniki"), "en_GB", "HER"),
        Destination("CZ", "Česko", "cs", "cs", "CZK", ("Praha", "Brno", "Špindlerův Mlýn"), "cs_CZ", "PRG"),
        Destination("HU", "Maďarsko", "en", "en", "HUF", ("Budapest", "Hévíz", "Siófok"), "hu_HU", "BUD"),
        Destination("TR", "Turecko", "en", "en", "TRY", ("Antalya", "Alanya", "Bodrum"), "tr_TR", "AYT"),
        Destination("US", "USA", "en", "en-us", "USD", ("New York", "Miami", "Orlando"), "en_US", "JFK"),
    ]
}  # fmt: skip


@dataclass
class Person:
    first_name: str
    last_name: str
    female: bool
    birth_date: date
    birth_number: str
    street: str
    city: str
    postcode: str
    phone: str
    email: str
    iban: str
    id_card: str
    czech: bool = False

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def address(self) -> str:
        return f"{self.street}, {self.postcode} {self.city}"


@dataclass
class Policy:
    policy_number: str
    product: Product
    kind: str  # single | annual
    start: date
    end: date
    issue_date: date
    premium: Decimal
    insured: list[Person]
    prior_paid: dict[Coverage, Decimal] = field(default_factory=dict)


@dataclass
class Item:
    """One claimed item: an invoice or receipt, a lost object, a fee, a fracture benefit."""

    ref: str
    description_sk: str
    coverage: Coverage
    category: str
    amount: Decimal  # in `currency`; for a fracture benefit, 0 (the product fixes the amount)
    currency: str
    doc_id: str | None
    verdict: CoverageVerdict = CoverageVerdict.COVERED
    clause_ids: list[str] = field(default_factory=list)
    exclusion: str | None = None
    valuables: bool = False
    expected_payout_eur: Decimal | None = None


@dataclass
class LineSpec:
    description: str
    amount: Decimal


@dataclass
class DocSpec:
    doc_id: str
    doc_type: DocType
    language: str
    locale: str
    scan: bool = False
    image_format: str | None = None  # "jpg" or "png" when delivered as a photo instead of a PDF
    handwriting: bool = False
    injection: str | None = None
    copy_of: str | None = None  # "<scenario_id>/<doc_id>": byte-identical resubmission
    reprint_of: str | None = None  # same invoice number, re-rendered
    data: dict = field(default_factory=dict)  # values the template prints


@dataclass
class Scenario:
    scenario_id: str
    split: str
    archetype: str
    claim_type: ClaimType
    product: Product
    person: Person
    policy: Policy
    destination: Destination
    city: str
    trip_start: date
    trip_end: date
    event_date: date
    event_datetime: datetime
    items: list[Item] = field(default_factory=list)
    docs: list[DocSpec] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)  # diagnosis, delay hours, cancellation reason...
    expected_queue: QueueName | None = None
    expected_status: ClaimStatus = ClaimStatus.IN_REVIEW
    expected_rule: str | None = None
    duplicate_of: str | None = None
    expected_total_payout_eur: Decimal | None = None
    expected_deductible_eur: Decimal = Decimal(0)
    expected_by_coverage: dict[str, Decimal] = field(default_factory=dict)
