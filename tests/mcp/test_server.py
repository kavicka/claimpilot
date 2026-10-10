"""MCP tools against a mocked review API."""

import httpx
import respx

from claimpilot_mcp import server

CLAIM = {
    "id": "c1",
    "reference": "CP-2026-000010",
    "status": "IN_REVIEW",
    "queue": "fraud_review",
    "error": None,  # the claim's own last pipeline error, not a lookup failure
    "routing": {"rule_hits": [{"rule": "R2", "detail": "14 days"}], "llm_used": False},
    "summaries": [{"kind": "client_letter", "text": "Vážená pani", "fact_violations": []}],
}


@respx.mock
async def test_tools_return_their_part_of_the_claim():
    respx.get(f"{server.API_URL}/api/review/claims/c1").mock(
        return_value=httpx.Response(200, json=CLAIM)
    )
    assert await server.explain_routing("c1") == {
        "queue": "fraud_review",
        "routing": CLAIM["routing"],
    }
    assert (await server.draft_client_letter("c1"))["letter"] == "Vážená pani"


@respx.mock
async def test_missing_claim_is_reported():
    respx.get(f"{server.API_URL}/api/review/claims/nope").mock(
        return_value=httpx.Response(404, json={"detail": "no such claim"})
    )
    assert await server.explain_routing("nope") == {"error": "no claim nope"}
