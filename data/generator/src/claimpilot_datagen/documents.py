"""Turn a DocSpec into what the template prints and what ground truth records.

For every field the ground truth keeps the string as printed and its normalized value (ISO date,
plain decimal, ISO currency or country code), so extraction can be scored on either.
"""

import random
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from claimpilot_core.domain import DocType
from claimpilot_core.identifiers import format_iban
from claimpilot_core.policy import ProductCatalog
from claimpilot_datagen import catalog as cat
from claimpilot_datagen.locale import LOCALES, fmt_amount, fmt_date, fmt_datetime
from claimpilot_datagen.model import DocSpec, LineSpec, Scenario
from claimpilot_datagen.narrative import Narrator

CURRENCY_PRINT = {
    "EUR": ["EUR", "€"],
    "CZK": ["Kč", "CZK"],
    "HUF": ["Ft", "HUF"],
    "TRY": ["TL", "TRY"],
    "USD": ["USD", "$"],
    "CHF": ["CHF", "Fr."],
}

COUNTRY_LOCAL = {
    "AT": "Österreich",
    "DE": "Deutschland",
    "CH": "Schweiz",
    "IT": "Italia",
    "HR": "Hrvatska",
    "CZ": "Česká republika",
    "ES": "Spain",
    "GR": "Greece",
    "HU": "Hungary",
    "TR": "Türkiye",
    "US": "USA",
    "SK": "Slovenská republika",
}

POLICY_KIND_SK = {"single": "jednorazové", "annual": "celoročné"}


@dataclass
class Built:
    template: str
    context: dict[str, Any]
    fields: dict[str, Any]
    pii: list[tuple[str, str]] = field(default_factory=list)  # (entity type, value as printed)


def gt(printed: str | None, norm: Any = None) -> dict[str, Any]:
    return {"printed": printed, "norm": norm if norm is not None else printed}


def iso(d: date | datetime | None) -> str | None:
    return d.isoformat() if d else None


def plain(amount: Decimal | None) -> str | None:
    return f"{amount:.2f}" if amount is not None else None


def pir_name(first: str, last: str, female: bool) -> str:
    def up(x: str) -> str:
        return unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().upper()

    return f"{up(last)}/{up(first)} {'MS' if female else 'MR'}"


class DocumentBuilder:
    def __init__(self, catalog: ProductCatalog, narrator: Narrator) -> None:
        self.catalog = catalog
        self.narrator = narrator

    def _rng(self, s: Scenario, d: DocSpec) -> random.Random:
        return random.Random(f"{s.scenario_id}/{d.doc_id}/{d.reprint_of or ''}")

    def build(self, s: Scenario, d: DocSpec) -> Built:
        fn = {
            DocType.CLAIM_FORM: self.claim_form,
            DocType.POLICY_CERTIFICATE: self.certificate,
            DocType.MEDICAL_REPORT: self.medical_report,
            DocType.MEDICAL_INVOICE: self.medical_invoice,
            DocType.PHARMACY_RECEIPT: self.pharmacy_receipt,
            DocType.PROPERTY_IRREGULARITY_REPORT: self.pir,
            DocType.POLICE_REPORT: self.police_report,
            DocType.BOOKING_CONFIRMATION: self.booking,
        }[d.doc_type]
        built = fn(s, d)
        built.context.setdefault("lang", d.language)
        built.context["injection"] = d.injection
        built.context["handwriting"] = d.handwriting
        return built

    # --- Slovak documents -----------------------------------------------------------------

    def claim_form(self, s: Scenario, d: DocSpec) -> Built:
        loc = LOCALES["sk"]
        p = s.person
        event_date: date = d.data["event_date"]
        rows = []
        for it in s.items:
            amount = fmt_amount(it.amount, loc) if it.amount else None
            rows.append(
                {
                    "description": it.description_sk,
                    "amount": amount,
                    "currency": it.currency if amount else None,
                    "_norm": plain(it.amount) if it.amount else None,
                }
            )
        description = self.narrator.claim_description(s, d)
        labels = [cat.CLAIM_TYPE_LABELS_SK[t] for t in d.data["claim_types"]]
        fields = {
            "policy_number": gt(s.policy.policy_number),
            "insured_name": gt(p.full_name),
            "insured_birth_number": gt(p.birth_number),
            "insured_address": gt(p.address),
            "insured_phone": gt(p.phone),
            "insured_email": gt(p.email),
            "iban": gt(format_iban(p.iban), p.iban),
            "destination_country": gt(s.destination.name_sk, s.destination.code),
            "trip_start": gt(fmt_date(s.trip_start, loc), iso(s.trip_start)),
            "trip_end": gt(fmt_date(s.trip_end, loc), iso(s.trip_end)),
            "event_date": gt(fmt_date(event_date, loc), iso(event_date)),
            "event_place": gt(f"{s.city}, {s.destination.name_sk}"),
            "claim_types": {"printed": labels, "norm": d.data["claim_types"]},
            "event_description": gt(description, None),
            "claimed_items": [
                {
                    "description": gt(r["description"]),
                    "amount": gt(r["amount"], r["_norm"]),
                    "currency": gt(r["currency"]),
                }
                for r in rows
            ],
            "signature_date": gt(
                fmt_date(d.data["signature_date"], loc), iso(d.data["signature_date"])
            ),
        }
        ctx = {f: v["printed"] for f, v in fields.items() if isinstance(v, dict) and "printed" in v}
        ctx.update(
            rows=rows,
            all_types=cat.CLAIM_TYPE_LABELS_SK,
            checked=d.data["claim_types"],
            insurer=self.catalog.insurer,
        )
        pii = [
            ("PERSON", p.full_name),
            ("BIRTH_NUMBER", p.birth_number),
            ("ADDRESS", p.street),
            ("PHONE", p.phone),
            ("EMAIL", p.email),
            ("IBAN", format_iban(p.iban)),
        ]
        return Built("claim_form.html.j2", ctx, fields, pii)

    def certificate(self, s: Scenario, d: DocSpec) -> Built:
        loc = LOCALES["sk"]
        pol = s.policy
        product = self.catalog.product(pol.product)
        fields = {
            "policy_number": gt(pol.policy_number),
            "product_name": gt(product.name, pol.product.value),
            "policy_type": gt(POLICY_KIND_SK[pol.kind], pol.kind),
            "policy_start": gt(fmt_date(pol.start, loc), iso(pol.start)),
            "policy_end": gt(fmt_date(pol.end, loc), iso(pol.end)),
            "insured_persons": [
                {"name": gt(x.full_name), "birth_number": gt(x.birth_number)} for x in pol.insured
            ],
            "premium": gt(f"{fmt_amount(pol.premium, loc)} EUR", plain(pol.premium)),
            "issue_date": gt(fmt_date(pol.issue_date, loc), iso(pol.issue_date)),
        }
        ctx = {f: v["printed"] for f, v in fields.items() if isinstance(v, dict)}
        ctx.update(
            insured=pol.insured,
            insurer=self.catalog.insurer,
            terms_id=self.catalog.terms_id,
            coverages=self._coverage_rows(pol.product.value, loc),
        )
        pii = [("PERSON", x.full_name) for x in pol.insured] + [
            ("BIRTH_NUMBER", x.birth_number) for x in pol.insured
        ]
        return Built("certificate.html.j2", ctx, fields, pii)

    def _coverage_rows(self, product: str, loc) -> list[dict]:
        names = {
            "medical": "Liečebné náklady",
            "accident": "Úraz – plnenie za zlomeninu",
            "luggage": "Batožina",
            "delay": "Oneskorenie batožiny",
            "cancellation": "Storno cesty",
            "liability": "Zodpovednosť za škodu",
        }
        rows = []
        for key, terms in self.catalog.product(product).coverages.items():
            if terms is None:
                rows.append({"name": names[key], "limit": "nedojednané", "deductible": "—"})
                continue
            limit = terms.limit or terms.fracture_benefit
            rows.append(
                {
                    "name": names[key],
                    "limit": f"{fmt_amount(limit, loc)} EUR" if limit else "—",
                    "deductible": f"{fmt_amount(terms.deductible, loc)} EUR"
                    if terms.deductible
                    else "bez spoluúčasti",
                }
            )
        return rows

    def booking(self, s: Scenario, d: DocSpec) -> Built:
        loc = LOCALES["sk"]
        fields = {
            "booking_number": gt(d.data["booking_number"]),
            "agency_name": gt(d.data["agency"]),
            "traveler_names": {"printed": [s.person.full_name], "norm": [s.person.full_name]},
            "destination": gt(d.data["destination"]),
            "trip_start": gt(fmt_date(s.trip_start, loc), iso(s.trip_start)),
            "trip_end": gt(fmt_date(s.trip_end, loc), iso(s.trip_end)),
            "total_price": gt(fmt_amount(d.data["price"], loc), plain(d.data["price"])),
            "currency": gt("EUR"),
            "cancellation_date": gt(
                fmt_date(d.data["cancellation_date"], loc), iso(d.data["cancellation_date"])
            ),
            "cancellation_fee": gt(fmt_amount(d.data["fee"], loc), plain(d.data["fee"])),
        }
        ctx = {f: v["printed"] for f, v in fields.items() if isinstance(v, dict)}
        ctx["travelers"] = [s.person.full_name]
        return Built("booking.html.j2", ctx, fields, [("PERSON", s.person.full_name)])

    # --- local-language documents ---------------------------------------------------------

    def medical_report(self, s: Scenario, d: DocSpec) -> Built:
        lang, loc = d.language, LOCALES[d.locale]
        dx = cat.DIAGNOSES[d.data["diagnosis"]]
        country = "SK" if lang == "sk" else s.destination.code
        anamnesis = (
            cat.ANAMNESIS[d.data["anamnesis"]].get(lang) or cat.ANAMNESIS[d.data["anamnesis"]]["en"]
        )
        treatment = self.narrator.medical_treatment(s, d)
        fields = {
            "facility_name": gt(d.data["facility"]),
            "facility_country": gt(COUNTRY_LOCAL[country], country),
            "patient_name": gt(s.person.full_name),
            "patient_birth_date": gt(fmt_date(s.person.birth_date, loc), iso(s.person.birth_date)),
            "visit_date": gt(fmt_date(d.data["visit_date"], loc), iso(d.data["visit_date"])),
            "discharge_date": gt(
                fmt_date(d.data["discharge_date"], loc), iso(d.data["discharge_date"])
            )
            if d.data["discharge_date"]
            else gt(None),
            "diagnosis": gt(dx.get(lang, dx["en"]), d.data["diagnosis"]),
            "icd10_code": gt(d.data["diagnosis"]),
            "anamnesis": gt(anamnesis, d.data["anamnesis"]),
            "treatment": gt(treatment, None),
            "physician_name": gt(d.data["physician"]),
        }
        ctx = {f: v["printed"] for f, v in fields.items()}
        ctx["city"] = d.data["city"]
        pii = [
            ("PERSON", s.person.full_name),
            ("PERSON", d.data["physician"].removeprefix("MUDr. ")),
            ("BIRTH_DATE", fields["patient_birth_date"]["printed"]),
        ]
        return Built("medical_report.html.j2", ctx, fields, pii)

    def _lines(self, lines: list[LineSpec], loc) -> tuple[list[dict], Decimal]:
        out = [
            {
                "description": gt(ln.description),
                "amount": gt(fmt_amount(ln.amount, loc), plain(ln.amount)),
            }
            for ln in lines
        ]
        return out, sum((ln.amount for ln in lines), Decimal(0))

    def medical_invoice(self, s: Scenario, d: DocSpec) -> Built:
        rng = self._rng(s, d)
        loc = LOCALES[d.locale]
        cur = d.data["currency"]
        cur_print = rng.choice(CURRENCY_PRINT[cur])
        lines, total = self._lines(d.data["lines"], loc)
        fields = {
            "invoice_number": gt(d.data["invoice_number"]),
            "issue_date": gt(fmt_date(d.data["issue_date"], loc), iso(d.data["issue_date"])),
            "provider_name": gt(d.data["provider"]),
            "provider_country": gt(COUNTRY_LOCAL[s.destination.code], s.destination.code),
            "patient_name": gt(s.person.full_name),
            "service_date": gt(fmt_date(d.data["service_date"], loc), iso(d.data["service_date"])),
            "currency": gt(cur_print, cur),
            "line_items": lines,
            "total": gt(fmt_amount(total, loc), plain(total)),
        }
        ctx = {f: v["printed"] for f, v in fields.items() if isinstance(v, dict)}
        ctx.update(
            lines=[{k: v["printed"] for k, v in ln.items()} for ln in lines],
            city=d.data["city"],
            style=d.data.get("style", "a"),
            patient_born=fmt_date(s.person.birth_date, loc),
        )
        pii = [("PERSON", s.person.full_name), ("BIRTH_DATE", ctx["patient_born"])]
        return Built("medical_invoice.html.j2", ctx, fields, pii)

    def pharmacy_receipt(self, s: Scenario, d: DocSpec) -> Built:
        rng = self._rng(s, d)
        loc = LOCALES[d.locale]
        cur = d.data["currency"]
        cur_print = rng.choice(CURRENCY_PRINT[cur])
        lines, total = self._lines(d.data["lines"], loc)
        dt: datetime = d.data["issue_datetime"]
        fields = {
            "receipt_number": gt(d.data["receipt_number"]),
            "issue_date": gt(fmt_datetime(dt, loc), iso(dt.date())),
            "pharmacy_name": gt(d.data["shop"]),
            "currency": gt(cur_print, cur),
            "line_items": lines,
            "total": gt(fmt_amount(total, loc), plain(total)),
        }
        ctx = {f: v["printed"] for f, v in fields.items() if isinstance(v, dict)}
        ctx.update(
            lines=[{k: v["printed"] for k, v in ln.items()} for ln in lines], city=d.data["city"]
        )
        return Built("pharmacy_receipt.html.j2", ctx, fields, [])

    def pir(self, s: Scenario, d: DocSpec) -> Built:
        loc = LOCALES["en-iso"]
        p = s.person
        name = pir_name(p.first_name, p.last_name, p.female)
        arrival: datetime = d.data["arrival"]
        delivery: datetime | None = d.data["delivery"]
        status = d.data["status"]
        remarks = (
            "Bag not delivered on arrival. Contents declared by passenger: "
            f"{', '.join(d.data['contents'])}."
            if status == "LOST"
            else "Bag missing on arrival, located at transfer station and forwarded to the "
            "passenger's hotel."
        )
        fields = {
            "file_reference": gt(d.data["file_reference"]),
            "airline": gt(d.data["airline"]),
            "flight_number": gt(d.data["flight_number"]),
            "flight_date": gt(fmt_date(d.data["flight_date"], loc), iso(d.data["flight_date"])),
            "passenger_name": gt(name, p.full_name),
            "bag_tag": gt(d.data["bag_tag"]),
            "status": gt(status, status.lower()),
            "arrival_time": gt(fmt_datetime(arrival, loc), arrival.isoformat(timespec="minutes")),
            "delivery_time": gt(fmt_datetime(delivery, loc), delivery.isoformat(timespec="minutes"))
            if delivery
            else gt(None),
            "remarks": gt(remarks, None),
        }
        ctx = {f: v["printed"] for f, v in fields.items()}
        ctx.update(
            airport=s.destination.airport,
            hotel_city=s.city,
            address=f"{p.street}, {p.city}",
            phone=p.phone,
        )
        pii = [("PERSON", name), ("ADDRESS", p.street), ("PHONE", p.phone)]
        return Built("pir.html.j2", ctx, fields, pii)

    def police_report(self, s: Scenario, d: DocSpec) -> Built:
        loc = LOCALES[d.locale]
        stolen = [
            {"description": gt(desc), "value": gt(f"{fmt_amount(v, loc)} EUR", plain(v))}
            for desc, v in d.data["stolen"]
        ]
        description = self.narrator.police_description(s, d)
        fields = {
            "report_number": gt(d.data["report_number"]),
            "report_date": gt(fmt_date(d.data["report_date"], loc), iso(d.data["report_date"])),
            "police_station": gt(d.data["station"]),
            "complainant_name": gt(s.person.full_name),
            "incident_date": gt(fmt_date(s.event_date, loc), iso(s.event_date)),
            "incident_place": gt(d.data["incident_place"]),
            "vehicle_plate": gt(d.data["vehicle_plate"]),
            "incident_description": gt(description, None),
            "stolen_items": stolen,
        }
        ctx = {f: v["printed"] for f, v in fields.items() if isinstance(v, dict)}
        ctx.update(
            stolen=[{k: v["printed"] for k, v in x.items()} for x in stolen],
            officer=d.data["officer"],
            birth=fmt_date(s.person.birth_date, loc),
            id_card=s.person.id_card,
            address=s.person.address,
        )
        pii = [
            ("PERSON", s.person.full_name),
            ("PERSON", d.data["officer"]),
            ("ID_CARD", s.person.id_card),
            ("ADDRESS", s.person.street),
            ("BIRTH_DATE", ctx["birth"]),
        ]
        if d.data["vehicle_plate"]:
            pii.append(("LICENCE_PLATE", d.data["vehicle_plate"]))
        return Built("police_report.html.j2", ctx, fields, pii)
