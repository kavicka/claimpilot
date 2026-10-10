"""Mock core claims system: the system of record a handler-approved claim is submitted to.

It behaves like the real thing is expected to: required fields, code lists, business validations
with field-level 422 errors, an Idempotency-Key header, attachments, and a published OpenAPI spec.
It knows nothing about ClaimPilot and imports none of its code.
"""

import hashlib
import json
import os
import uuid
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="Core Claims System (mock)",
    version="1.0.0",
    description="System of record for travel claims. Submissions are validated field by field.",
)

CODE_LISTS: dict[str, dict[str, str]] = {
    "claim_type": {
        "MED": "medical expenses",
        "ACC": "accident",
        "LUG": "luggage",
        "DLY": "luggage delay",
        "CXL": "trip cancellation",
        "LIA": "liability",
    },
    "coverage": {
        "MED": "medical",
        "ACC": "accident",
        "LUG": "luggage",
        "DLY": "delay",
        "CXL": "cancellation",
        "LIA": "liability",
    },
    "country": {
        c: c
        for c in [
            "AT",
            "DE",
            "CH",
            "IT",
            "HR",
            "ES",
            "GR",
            "CZ",
            "HU",
            "TR",
            "US",
            "SK",
            "PL",
            "SI",
            "FR",
            "GB",
            "PT",
            "EG",
            "TH",
        ]
    },
    "currency": {"EUR": "euro"},
    "decision": {"PAY": "pay", "DECLINE": "decline"},
}
COVERAGE_KEY = {
    "MED": "medical",
    "ACC": "accident",
    "LUG": "luggage",
    "DLY": "delay",
    "CXL": "cancellation",
    "LIA": "liability",
}
IBAN_LENGTHS = {"SK": 24, "CZ": 24, "AT": 20, "DE": 22, "IT": 27, "HR": 21, "HU": 28, "PL": 28}
STORE: dict[str, Any] = {}


@lru_cache
def policies() -> dict[str, dict]:
    path = Path(os.environ.get("CORE_MOCK_POLICIES", "/app/data/policies.json"))
    return (
        {p["policy_number"]: p for p in json.loads(path.read_text("utf-8"))}
        if path.exists()
        else {}
    )


@lru_cache
def products() -> dict[str, dict]:
    path = Path(os.environ.get("CORE_MOCK_PRODUCTS", "/app/data/products.yaml"))
    return yaml.safe_load(path.read_text("utf-8"))["products"] if path.exists() else {}


def iban_ok(value: str) -> bool:
    s = value.replace(" ", "").upper()
    if IBAN_LENGTHS.get(s[:2]) != len(s) or not s.isalnum():
        return False
    return int("".join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97 == 1


class Insured(BaseModel):
    name: str
    birth_number: str


class Item(BaseModel):
    ref: str
    coverage_code: str
    claimed_eur: Decimal = Field(ge=0)
    payout_eur: Decimal = Field(ge=0)
    decision: Literal["PAY", "DECLINE"]
    clause_refs: list[str] = Field(default_factory=list)


class ClaimSubmission(BaseModel):
    policy_number: str
    claim_type_code: str
    insured: Insured
    event_date: date
    event_country: str
    iban: str
    currency: str
    total_payout: Decimal = Field(ge=0)
    items: list[Item]
    handler_id: str
    notes: str | None = None


class Registered(BaseModel):
    core_claim_id: str
    status: Literal["REGISTERED"]
    policy_number: str
    total_payout: Decimal


def _err(loc: list, msg: str, kind: str) -> dict:
    return {"loc": ["body", *loc], "msg": msg, "type": kind}


def validate(sub: ClaimSubmission) -> list[dict]:
    errors = []
    if sub.claim_type_code not in CODE_LISTS["claim_type"]:
        errors.append(
            _err(
                ["claim_type_code"],
                f"use one of {sorted(CODE_LISTS['claim_type'])}",
                "not_in_code_list",
            )
        )
    if sub.event_country not in CODE_LISTS["country"]:
        errors.append(_err(["event_country"], "ISO 3166 alpha-2 code expected", "not_in_code_list"))
    if sub.currency not in CODE_LISTS["currency"]:
        errors.append(_err(["currency"], "payouts are made in EUR", "not_in_code_list"))
    if not iban_ok(sub.iban):
        errors.append(_err(["iban"], "IBAN checksum or length is wrong", "invalid_iban"))
    policy = policies().get(sub.policy_number)
    if policy is None:
        errors.append(_err(["policy_number"], "no such policy", "unknown_policy"))
        return errors
    if sub.insured.birth_number not in {p["birth_number"] for p in policy["insured"]}:
        errors.append(
            _err(
                ["insured", "birth_number"],
                "person is not insured on this policy",
                "not_insured_on_policy",
            )
        )
    # A declined claim is registered too, whatever its date. Cancellation cover starts when the
    # policy is issued, because the reason to cancel arises before the trip.
    starts = policy["issue_date"] if sub.claim_type_code == "CXL" else policy["start"]
    paying = any(i.payout_eur > 0 for i in sub.items)
    if paying and not (
        date.fromisoformat(starts) <= sub.event_date <= date.fromisoformat(policy["end"])
    ):
        errors.append(
            _err(
                ["event_date"],
                f"cover runs {starts} to {policy['end']}",
                "outside_policy_period",
            )
        )
    paid = sum((i.payout_eur for i in sub.items), Decimal(0))
    if paid != sub.total_payout:
        errors.append(_err(["total_payout"], f"items add up to {paid}", "does_not_match_items"))
    terms = products().get(policy["product"], {}).get("coverages", {})
    for n, item in enumerate(sub.items):
        if item.coverage_code not in CODE_LISTS["coverage"]:
            errors.append(
                _err(["items", n, "coverage_code"], "unknown coverage", "not_in_code_list")
            )
            continue
        cov = COVERAGE_KEY[item.coverage_code]
        t = terms.get(cov)
        if t is None and item.payout_eur > 0:
            errors.append(
                _err(
                    ["items", n, "coverage_code"],
                    f"{cov} is not included in {policy['product']}",
                    "not_covered_by_product",
                )
            )
            continue
        limit = (t or {}).get("limit")
        if limit is not None:
            remaining = Decimal(str(limit)) - Decimal(str(policy["prior_paid"].get(cov, 0)))
            if item.payout_eur > remaining:
                errors.append(
                    _err(
                        ["items", n, "payout_eur"],
                        f"remaining limit is {remaining}",
                        "above_remaining_limit",
                    )
                )
        if item.decision == "DECLINE" and item.payout_eur > 0:
            errors.append(
                _err(
                    ["items", n, "payout_eur"],
                    "a declined item pays nothing",
                    "declined_with_payout",
                )
            )
    return errors


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "Not found"}}


@app.get("/codelists/{name}", responses=NOT_FOUND)
async def code_list(name: str) -> dict[str, str]:
    if name not in CODE_LISTS:
        raise HTTPException(404, f"code lists: {sorted(CODE_LISTS)}")
    return CODE_LISTS[name]


@app.get("/policies/{policy_number}", responses=NOT_FOUND)
async def get_policy(policy_number: str) -> dict:
    policy = policies().get(policy_number)
    if policy is None:
        raise HTTPException(404, "no such policy")
    terms = products().get(policy["product"], {}).get("coverages", {})
    remaining = {
        cov: str(Decimal(str(t["limit"])) - Decimal(str(policy["prior_paid"].get(cov, 0))))
        for cov, t in terms.items()
        if t and t.get("limit") is not None
    }
    return {**policy, "remaining": remaining}


@app.post(
    "/claims",
    status_code=201,
    response_model=Registered,
    responses={
        400: {"description": "Idempotency-Key header missing"},
        409: {"description": "Idempotency-Key reused with another body"},
        422: {"description": "Field-level validation errors"},
    },
)
async def submit_claim(sub: ClaimSubmission, idempotency_key: str | None = Header(None)) -> Any:
    if not idempotency_key:
        raise HTTPException(400, "Idempotency-Key header is required")
    fingerprint = hashlib.sha256(sub.model_dump_json().encode()).hexdigest()
    previous = STORE.get(f"idem:{idempotency_key}")
    if previous:
        if previous["fingerprint"] != fingerprint:
            raise HTTPException(409, "Idempotency-Key was used with a different request")
        return JSONResponse(previous["response"], status_code=201)
    errors = validate(sub)
    if errors:
        return JSONResponse({"detail": errors}, status_code=422)
    core_id = f"CCS-{uuid.uuid4().hex[:10].upper()}"
    response = {
        "core_claim_id": core_id,
        "status": "REGISTERED",
        "policy_number": sub.policy_number,
        "total_payout": str(sub.total_payout),
    }
    STORE[core_id] = {
        "submission": json.loads(sub.model_dump_json()),
        "attachments": [],
        **response,
    }
    STORE[f"idem:{idempotency_key}"] = {"fingerprint": fingerprint, "response": response}
    return JSONResponse(response, status_code=201)


@app.post(
    "/claims/{core_claim_id}/attachments",
    status_code=201,
    responses={**NOT_FOUND, 400: {"description": "Malformed multipart body"}},
)
async def upload_attachment(core_claim_id: str, file: UploadFile = File(...)) -> dict:  # noqa: B008
    claim = STORE.get(core_claim_id)
    if claim is None:
        raise HTTPException(404, "no such claim")
    await file.read()
    claim["attachments"].append(file.filename)
    return {"core_claim_id": core_claim_id, "attachments": len(claim["attachments"])}


@app.get("/claims/{core_claim_id}", responses=NOT_FOUND)
async def get_claim(core_claim_id: str) -> dict:
    claim = STORE.get(core_claim_id)
    if claim is None:
        raise HTTPException(404, "no such claim")
    return claim
