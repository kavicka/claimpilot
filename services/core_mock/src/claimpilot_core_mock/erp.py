"""Mock ERP of the buyer group: suppliers, orders and goods receipts that invoices are matched
against (stage 3.6), and later the UBL intake (stage 3.8).

A separate system from the core claims mock; it shares only the package for building. It knows
nothing about ClaimPilot and imports none of its code. Records come from the synthetic invoice
set (data/synthetic/invoices/erp-*.json); every split the directory holds is loaded.
"""

import hashlib
import hmac
import json
import os
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(
    title="ERP (mock)",
    version="1.0.0",
    description="Suppliers, purchase orders and goods receipts of the buyer group.",
)
NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "No such record"}}


@app.middleware("http")
async def require_token(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """With ERP_MOCK_TOKEN set, every call but /health carries `Authorization: Bearer <token>`.
    The token is read per request, so a test or a rotated secret needs no restart."""
    token = os.environ.get("ERP_MOCK_TOKEN", "")
    if token and request.url.path != "/health":
        given = request.headers.get("authorization", "")
        if not hmac.compare_digest(given.encode(), f"Bearer {token}".encode()):
            return JSONResponse(
                {"detail": "missing or wrong bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)


@lru_cache
def records() -> dict[str, Any]:
    root = Path(os.environ.get("ERP_MOCK_DATA", "/app/data/invoices"))
    out: dict[str, Any] = {"suppliers": {}, "orders": {}, "receipts": {}}
    for path in sorted(root.glob("erp-*.json")):
        data = json.loads(path.read_text("utf-8"))
        for s in data["suppliers"]:
            out["suppliers"][s["ico"]] = s
        for o in data["orders"]:
            out["orders"][o["number"]] = o
        for r in data["receipts"]:
            out["receipts"].setdefault(r["order_number"], []).append(r)
    return out


@app.get("/health")
async def health() -> dict[str, Any]:
    r = records()
    return {"status": "ok", "suppliers": len(r["suppliers"]), "orders": len(r["orders"])}


@app.get("/suppliers", responses=NOT_FOUND)
async def supplier(
    ico: str | None = Query(None), vat_id: str | None = Query(None)
) -> dict[str, Any]:
    """A supplier by VAT id, else by IČO."""
    suppliers = records()["suppliers"].values()
    found = next((s for s in suppliers if vat_id and s["vat_id"] == vat_id), None) or next(
        (s for s in suppliers if ico and s["ico"] == ico), None
    )
    if found is None:
        raise HTTPException(404, "no such supplier")
    return found


@app.get("/orders/{number}", responses=NOT_FOUND)
async def order(number: str) -> dict[str, Any]:
    found = records()["orders"].get(number)
    if found is None:
        raise HTTPException(404, "no such order")
    return found


@app.get("/orders/{number}/receipts")
async def receipts(number: str) -> list[dict[str, Any]]:
    return records()["receipts"].get(number, [])


POSTED: dict[str, dict[str, Any]] = {}  # erp id -> posted document (memory: a mock)
KEYS: dict[str, dict[str, Any]] = {}  # idempotency key -> {erp_id, sha256 of the XML, kind}


def refusal(status: int, rule: str, message: str, **extra: Any) -> HTTPException:
    errors = [{"rule": rule, "field": "body", "message": message}]
    return HTTPException(status, {"errors": errors, **extra})


@app.post(
    "/invoices",
    status_code=201,
    responses={
        200: {"description": "Repeated Idempotency-Key: the first answer again"},
        409: {"description": "Another document with this supplier and number is posted"},
        422: {"description": "Rules broken, or the key was used for other content"},
    },
)
async def post_invoice(request: Request) -> JSONResponse:
    """Accept a Peppol BIS Billing 3.0 invoice or credit note (UBL 2.1). A refusal lists every
    broken rule with the field it concerns. `Idempotency-Key` makes a repeat safe: the same key
    and content get the first answer (200) and store nothing; the same key with other content is
    refused; a different key for a document that is posted already is a 409 naming its erp_id."""
    from claimpilot_core_mock.ubl_rules import _text, check, parse

    body = await request.body()
    digest = hashlib.sha256(body).hexdigest()
    idem = request.headers.get("idempotency-key")
    if idem and (seen := KEYS.get(idem)):
        if seen["sha256"] != digest:
            raise refusal(
                422, "idempotency_key_reused", "this Idempotency-Key was used for other content"
            )
        return JSONResponse({"erp_id": seen["erp_id"], "kind": seen["kind"]}, status_code=200)
    try:
        root = parse(body)
    except (ValueError, ET.ParseError) as exc:
        raise refusal(422, "XML", str(exc)) from exc
    kind, errors = check(root)
    vat_id = _text(root, "AccountingSupplierParty/Party/PartyTaxScheme/CompanyID")
    ico = _text(root, "AccountingSupplierParty/Party/PartyLegalEntity/CompanyID")
    known = records()["suppliers"].values()
    if not any((vat_id and s["vat_id"] == vat_id) or (ico and s["ico"] == ico) for s in known):
        errors.append(
            {
                "rule": "ERP-SUPPLIER",
                "field": "AccountingSupplierParty",
                "message": "supplier not in the ERP",
            }
        )
    if errors:
        raise HTTPException(422, {"errors": errors})
    number = _text(root, "ID")
    key = f"{vat_id or ico}:{number}:{kind}"
    existing = next((i for i, p in POSTED.items() if p["key"] == key), None)
    if existing is not None:
        raise refusal(
            409,
            "ERP-DUPLICATE",
            f"{kind} {number} of this supplier is posted already as {existing}",
            erp_id=existing,
        )
    erp_id = f"ERP-{len(POSTED) + 1:06d}"
    POSTED[erp_id] = {"key": key, "kind": kind, "number": number}
    if idem:
        KEYS[idem] = {"erp_id": erp_id, "sha256": digest, "kind": kind}
    return JSONResponse({"erp_id": erp_id, "kind": kind}, status_code=201)
