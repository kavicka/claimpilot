"""Read-only MCP server over the ClaimPilot API.

Agents can list claims, read them (personal data stays tokenized), see extracted fields, coverage,
routing and the draft client letter. There is no approve, reject or submit tool, by design: human
approval stays in the review UI and every decision has a handler in the audit log.

    claimpilot-mcp                       # stdio, for Claude Code / Claude Desktop
    claimpilot-mcp --transport http      # streamable HTTP on :4402
"""

import argparse
import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

API_URL = os.environ.get("CLAIMPILOT_API_URL", "http://127.0.0.1:4400")
TOKEN = os.environ.get("CLAIMPILOT_MCP_TOKEN", "")

mcp = MCPServer(
    name="claimpilot",
    instructions=(
        "Read-only access to ClaimPilot travel-insurance claims. Personal data appears as tokens "
        "such as <PERSON_1>. No tool can approve, reject or submit a claim; a handler does that in "
        "the review UI. Queues: fast_track, standard, senior, fraud_review."
    ),
)


async def _get(path: str, **params: Any) -> Any:
    async with httpx.AsyncClient(
        base_url=API_URL, timeout=30, headers={"X-Service-Token": TOKEN}
    ) as client:
        resp = await client.get(path, params={k: v for k, v in params.items() if v is not None})
        resp.raise_for_status()
        return resp.json()


async def _claim(claim_id: str) -> dict[str, Any] | None:
    """The claim, or None when there is no such claim. (A claim has its own "error" field, the
    last pipeline error, so a missing claim must not be signalled with that key.)"""
    try:
        return await _get(f"/api/review/claims/{claim_id}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 422):
            return None
        raise


def _missing(claim_id: str) -> dict[str, str]:
    return {"error": f"no claim {claim_id}"}


@mcp.tool(
    description="List claims, optionally one queue: fast_track, standard, senior, fraud_review."
)
async def list_claims(queue: str | None = None) -> list[dict[str, Any]]:
    rows = await _get("/api/review/claims", queue=queue)
    keep = (
        "id",
        "reference",
        "status",
        "queue",
        "claim_type",
        "product",
        "claimed_total_eur",
        "payout_eur",
    )
    return [{k: r.get(k) for k in keep} for r in rows]


@mcp.tool(
    description="One claim: status, queue, totals and pipeline steps. Personal data is tokenized."
)
async def get_claim(claim_id: str) -> dict[str, Any]:
    c = await _claim(claim_id)
    if c is None:
        return _missing(claim_id)
    keep = (
        "id",
        "reference",
        "status",
        "queue",
        "claim_type",
        "product",
        "assessment",
        "error",
        "steps",
    )
    return {k: c.get(k) for k in keep} | {
        "documents": [
            {"doc_type": d["doc_type"], "language": d["language"]} for d in c["documents"]
        ]
    }


@mcp.tool(
    description="Fields extracted from each document of a claim, with confidence and grounding."
)
async def extract_documents(claim_id: str) -> list[dict[str, Any]]:
    c = await _claim(claim_id)
    if c is None:
        return [_missing(claim_id)]
    return [
        {
            "doc_type": d["doc_type"],
            "fields": [
                {k: f[k] for k in ("field", "value", "confidence", "grounded")}
                for f in d["fields"]
                if f["value"] is not None
            ],
        }
        for d in c["documents"]
    ]


@mcp.tool(
    description="Coverage per claimed item: verdict, deciding clauses, payout and its explanation."
)
async def check_coverage(claim_id: str) -> dict[str, Any]:
    c = await _claim(claim_id)
    if c is None:
        return _missing(claim_id)
    return {"items": c["coverage"], "assessment": c["assessment"]}


@mcp.tool(
    description="Why the claim is in its queue: the routing rules that fired and the rationale."
)
async def explain_routing(claim_id: str) -> dict[str, Any]:
    c = await _claim(claim_id)
    if c is None:
        return _missing(claim_id)
    return {"queue": c["queue"], "routing": c["routing"]}


@mcp.tool(description="The draft decision letter to the client (Slovak) that the handler reviews.")
async def draft_client_letter(claim_id: str) -> dict[str, Any]:
    c = await _claim(claim_id)
    if c is None:
        return _missing(claim_id)
    letter = next((s for s in c["summaries"] if s["kind"] == "client_letter"), None)
    return {
        "letter": letter["text"] if letter else None,
        "fact_violations": letter["fact_violations"] if letter else [],
    }


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4402)
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run("stdio")
    else:
        mcp.run("streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
