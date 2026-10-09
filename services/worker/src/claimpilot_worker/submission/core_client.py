"""HTTP client for the core claims system (core_mock in Phase 1)."""

from typing import Any

import httpx


class CoreClient:
    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def code_list(self, name: str) -> dict[str, str]:
        resp = await self._client.get(f"/codelists/{name}")
        resp.raise_for_status()
        return resp.json()

    async def policy(self, policy_number: str) -> dict[str, Any] | None:
        resp = await self._client.get(f"/policies/{policy_number}")
        return resp.json() if resp.status_code == 200 else None

    async def submit(
        self, payload: dict[str, Any], idempotency_key: str
    ) -> tuple[int, dict[str, Any]]:
        resp = await self._client.post(
            "/claims", json=payload, headers={"Idempotency-Key": idempotency_key}
        )
        return resp.status_code, resp.json()
