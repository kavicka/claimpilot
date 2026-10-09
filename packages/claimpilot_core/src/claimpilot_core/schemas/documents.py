"""Field sets per document type.

Every value is a string exactly as printed on the document (ADR-002): "1.279,50", "14.02.2026".
Validators and normalizers in the worker turn them into Decimal amounts, ISO dates and codes.
The field descriptions go into the extraction prompt, so they are written for the model.
"""

from pydantic import BaseModel, Field

from claimpilot_core.domain import DocType

Printed = str | None


class LineItem(BaseModel):
    description: Printed = Field(None, description="Item or service text as printed")
    amount: Printed = Field(None, description="Amount as printed, without currency symbol")


class ClaimedItem(BaseModel):
    description: Printed = Field(None, description="What the client claims, as written")
    amount: Printed = Field(None, description="Claimed amount as written")
    currency: Printed = Field(None, description="Currency as written next to the amount")


class InsuredPerson(BaseModel):
    name: Printed = Field(None, description="Full name of the insured person")
    birth_number: Printed = Field(None, description="Rodné číslo / birth number as printed")


class StolenItem(BaseModel):
    description: Printed = Field(None, description="Stolen item as listed")
    value: Printed = Field(None, description="Stated value as printed")


class ClaimForm(BaseModel):
    """Hlásenie poistnej udalosti, filled in by the client (Slovak)."""

    policy_number: Printed = Field(None, description="Číslo poistnej zmluvy")
    insured_name: Printed = Field(None, description="Meno a priezvisko poisteného")
    insured_birth_number: Printed = Field(None, description="Rodné číslo poisteného")
    insured_address: Printed = Field(None, description="Adresa poisteného, one line")
    insured_phone: Printed = Field(None, description="Telefón")
    insured_email: Printed = Field(None, description="E-mail")
    iban: Printed = Field(None, description="IBAN for the payout")
    destination_country: Printed = Field(None, description="Krajina cesty as written")
    trip_start: Printed = Field(None, description="Cesta od (date)")
    trip_end: Printed = Field(None, description="Cesta do (date)")
    event_date: Printed = Field(None, description="Dátum vzniku udalosti")
    event_place: Printed = Field(None, description="Miesto vzniku udalosti")
    claim_types: list[str] = Field(
        default_factory=list, description="Checked boxes in 'Druh udalosti', labels as printed"
    )
    event_description: Printed = Field(None, description="Popis udalosti, full text")
    claimed_items: list[ClaimedItem] = Field(
        default_factory=list, description="Rows of the 'Uplatňované náklady / veci' table"
    )
    signature_date: Printed = Field(None, description="Dátum podpisu")


class PolicyCertificate(BaseModel):
    """Poistný certifikát (Slovak)."""

    policy_number: Printed = Field(None, description="Číslo poistnej zmluvy")
    product_name: Printed = Field(
        None, description="Product name, e.g. 'Cestovné poistenie Standard'"
    )
    policy_type: Printed = Field(None, description="Druh poistenia: jednorazové or celoročné")
    policy_start: Printed = Field(None, description="Začiatok poistenia (date)")
    policy_end: Printed = Field(None, description="Koniec poistenia (date)")
    insured_persons: list[InsuredPerson] = Field(default_factory=list)
    premium: Printed = Field(None, description="Poistné, amount as printed")
    issue_date: Printed = Field(None, description="Dátum uzavretia / vystavenia")


class MedicalReport(BaseModel):
    """Medical report from a clinic or hospital (DE, IT, HR, EN, SK)."""

    facility_name: Printed = Field(None, description="Clinic or hospital name")
    facility_country: Printed = Field(None, description="Country from the facility address")
    patient_name: Printed = Field(None, description="Patient name")
    patient_birth_date: Printed = Field(None, description="Patient date of birth as printed")
    visit_date: Printed = Field(None, description="Date of examination or admission")
    discharge_date: Printed = Field(None, description="Discharge date, only if hospitalized")
    diagnosis: Printed = Field(None, description="Diagnosis text as printed")
    icd10_code: Printed = Field(None, description="ICD-10 code, e.g. S52.5")
    anamnesis: Printed = Field(None, description="Anamnesis / history section, full text")
    treatment: Printed = Field(None, description="Findings and treatment section, full text")
    physician_name: Printed = Field(None, description="Signing physician")


class MedicalInvoice(BaseModel):
    """Invoice from a clinic or hospital, possibly several pages of line items."""

    invoice_number: Printed = Field(None, description="Invoice number")
    issue_date: Printed = Field(None, description="Invoice date")
    provider_name: Printed = Field(None, description="Issuing clinic or hospital")
    provider_country: Printed = Field(None, description="Country from the provider address")
    patient_name: Printed = Field(None, description="Patient name")
    service_date: Printed = Field(None, description="Date of treatment, if printed")
    currency: Printed = Field(None, description="Currency code or symbol as printed")
    line_items: list[LineItem] = Field(default_factory=list, description="Every billed line")
    total: Printed = Field(None, description="Total amount due as printed")


class PharmacyReceipt(BaseModel):
    """Receipt from a pharmacy or drugstore."""

    receipt_number: Printed = Field(None, description="Receipt or document number")
    issue_date: Printed = Field(None, description="Receipt date")
    pharmacy_name: Printed = Field(None, description="Shop name")
    currency: Printed = Field(None, description="Currency as printed")
    line_items: list[LineItem] = Field(default_factory=list)
    total: Printed = Field(None, description="Total as printed")


class PropertyIrregularityReport(BaseModel):
    """Airline Property Irregularity Report (English)."""

    file_reference: Printed = Field(None, description="PIR file reference, e.g. VIEOS12345")
    airline: Printed = Field(None, description="Airline name")
    flight_number: Printed = Field(None, description="Flight number")
    flight_date: Printed = Field(None, description="Flight date")
    passenger_name: Printed = Field(None, description="Passenger name")
    bag_tag: Printed = Field(None, description="Bag tag number")
    status: Printed = Field(None, description="Bag status: delayed, lost or damaged, as printed")
    arrival_time: Printed = Field(None, description="Passenger arrival date and time")
    delivery_time: Printed = Field(None, description="Bag delivery date and time, if delivered")
    remarks: Printed = Field(None, description="Remarks section, full text")


class PoliceReport(BaseModel):
    """Police theft report in the local language."""

    report_number: Printed = Field(None, description="Report or case number")
    report_date: Printed = Field(None, description="Date the report was filed")
    police_station: Printed = Field(None, description="Police station or unit")
    complainant_name: Printed = Field(None, description="Name of the person reporting")
    incident_date: Printed = Field(None, description="Date of the theft")
    incident_place: Printed = Field(None, description="Place of the theft")
    vehicle_plate: Printed = Field(None, description="Licence plate, only if a vehicle is involved")
    incident_description: Printed = Field(None, description="Description of the incident")
    stolen_items: list[StolenItem] = Field(default_factory=list)


class BookingConfirmation(BaseModel):
    """Booking and cancellation confirmation from a travel agency."""

    booking_number: Printed = Field(None, description="Booking number")
    agency_name: Printed = Field(None, description="Travel agency")
    traveler_names: list[str] = Field(default_factory=list, description="Travellers as listed")
    destination: Printed = Field(None, description="Destination as printed")
    trip_start: Printed = Field(None, description="Departure date")
    trip_end: Printed = Field(None, description="Return date")
    total_price: Printed = Field(None, description="Total trip price as printed")
    currency: Printed = Field(None, description="Currency as printed")
    cancellation_date: Printed = Field(None, description="Date of cancellation")
    cancellation_fee: Printed = Field(None, description="Cancellation fee charged, as printed")


SCHEMAS: dict[DocType, type[BaseModel]] = {
    DocType.CLAIM_FORM: ClaimForm,
    DocType.POLICY_CERTIFICATE: PolicyCertificate,
    DocType.MEDICAL_REPORT: MedicalReport,
    DocType.MEDICAL_INVOICE: MedicalInvoice,
    DocType.PHARMACY_RECEIPT: PharmacyReceipt,
    DocType.PROPERTY_IRREGULARITY_REPORT: PropertyIrregularityReport,
    DocType.POLICE_REPORT: PoliceReport,
    DocType.BOOKING_CONFIRMATION: BookingConfirmation,
}

# Fields whose errors change a decision; extraction accuracy is gated on these.
CRITICAL_FIELDS: dict[DocType, list[str]] = {
    DocType.CLAIM_FORM: ["policy_number", "event_date", "iban", "trip_start", "trip_end"],
    DocType.POLICY_CERTIFICATE: ["policy_number", "product_name", "policy_start", "policy_end"],
    DocType.MEDICAL_REPORT: ["visit_date", "diagnosis", "icd10_code"],
    DocType.MEDICAL_INVOICE: ["invoice_number", "issue_date", "currency", "total"],
    DocType.PHARMACY_RECEIPT: ["issue_date", "currency", "total"],
    DocType.PROPERTY_IRREGULARITY_REPORT: ["file_reference", "status", "arrival_time"],
    DocType.POLICE_REPORT: ["report_number", "incident_date"],
    DocType.BOOKING_CONFIRMATION: ["booking_number", "cancellation_date", "cancellation_fee"],
}
