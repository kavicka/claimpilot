"""Mock ERP of the buyer group: suppliers, orders and goods receipts that invoices are matched
against (stage 3.6), and later the UBL intake (stage 3.8).

A separate system from the core claims mock; it shares only the package for building. It knows
nothing about ClaimPilot and imports none of its code. Records come from the synthetic invoice
set (data/synthetic/invoices/erp-*.json); every split the directory holds is loaded.
"""

import json
import os
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request

app = FastAPI(
    title="ERP (mock)",
    version="1.0.0",
    description="Suppliers, purchase orders and goods receipts of the buyer group.",
)
NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"description": "No such record"}}


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


@app.post(
    "/invoices",
    status_code=201,
    responses={409: {"description": "Already posted"}, 422: {"description": "Rules broken"}},
)
async def post_invoice(request: Request) -> dict[str, Any]:
    """Accept a Peppol BIS Billing 3.0 invoice or credit note (UBL 2.1). A refusal lists every
    broken rule with the field it concerns."""
    from claimpilot_core_mock.ubl_rules import _text, check, parse

    body = await request.body()
    try:
        root = parse(body)
    except (ValueError, ET.ParseError) as exc:
        raise HTTPException(
            422, {"errors": [{"rule": "XML", "field": "body", "message": str(exc)}]}
        ) from exc
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
    if any(p["key"] == key for p in POSTED.values()):
        raise HTTPException(409, "this document was posted already")
    erp_id = f"ERP-{len(POSTED) + 1:06d}"
    POSTED[erp_id] = {"key": key, "kind": kind, "number": number}
    return {"erp_id": erp_id, "kind": kind}
