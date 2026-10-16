"""Domain vocabulary shared by every service.

Enums here are the closed sets that prompts, routing rules, the database and the UI agree on.
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class CaseKind(StrEnum):
    """What a case is. Documents, fields, vault entries and step runs hang off a case."""

    CLAIM = "claim"
    INVOICE = "invoice"


class ClaimStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PARSED = "PARSED"
    REDACTED = "REDACTED"
    EXTRACTED = "EXTRACTED"
    ROUTED = "ROUTED"
    ASSESSED = "ASSESSED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    NEEDS_INFO = "NEEDS_INFO"
    FAILED = "FAILED"


class InvoiceStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PARSED = "PARSED"
    REDACTED = "REDACTED"
    EXTRACTED = "EXTRACTED"
    VALIDATED = "VALIDATED"
    MATCHED = "MATCHED"
    ROUTED = "ROUTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    EXPORTED = "EXPORTED"
    REJECTED = "REJECTED"
    NEEDS_INFO = "NEEDS_INFO"
    FAILED = "FAILED"


class Queue(StrEnum):
    FAST_TRACK = "fast_track"
    STANDARD = "standard"
    SENIOR = "senior"
    FRAUD_REVIEW = "fraud_review"


class ClaimType(StrEnum):
    MEDICAL = "medical"
    LUGGAGE = "luggage"
    CANCELLATION = "cancellation"
    ACCIDENT = "accident"


class DocType(StrEnum):
    CLAIM_FORM = "claim_form"
    POLICY_CERTIFICATE = "policy_certificate"
    MEDICAL_REPORT = "medical_report"
    MEDICAL_INVOICE = "medical_invoice"
    PHARMACY_RECEIPT = "pharmacy_receipt"
    PROPERTY_IRREGULARITY_REPORT = "property_irregularity_report"
    POLICE_REPORT = "police_report"
    BOOKING_CONFIRMATION = "booking_confirmation"


class Product(StrEnum):
    BASIC = "basic"
    STANDARD = "standard"
    PREMIUM = "premium"


class Coverage(StrEnum):
    """Coverage sections of the policy; every claimed item maps to exactly one."""

    MEDICAL = "medical"
    LUGGAGE = "luggage"
    DELAY = "delay"
    CANCELLATION = "cancellation"
    ACCIDENT = "accident"
    LIABILITY = "liability"


class CoverageVerdict(StrEnum):
    COVERED = "covered"
    NOT_COVERED = "not_covered"
    NEEDS_REVIEW = "needs_review"


class ExtractionMethod(StrEnum):
    RULE = "rule"
    LLM_TEXT = "llm_text"
    LLM_VISION = "llm_vision"
    HANDLER = "handler"


class PipelineStep(StrEnum):
    INGEST = "ingest"
    REDACT = "redact"
    EXTRACT = "extract"
    VALIDATE = "validate"
    MATCH = "match"
    ROUTE = "route"
    ASSESS = "assess"
    SUMMARIZE = "summarize"
    SUBMIT = "submit"


class BBox(BaseModel):
    """Rectangle on a page in PDF points, origin top-left."""

    x0: float
    y0: float
    x1: float
    y1: float


class Money(BaseModel):
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)


class Trip(BaseModel):
    destination_country: str = Field(min_length=2, max_length=2)
    start: date
    end: date
