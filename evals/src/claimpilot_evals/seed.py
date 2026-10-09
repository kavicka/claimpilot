"""Upload synthetic claims through the api, the way a portal would."""

import httpx

from claimpilot_core.settings import get_settings
from claimpilot_evals.dataset import Dataset


def seed(split: str, n: int, ids: list[str] | None = None) -> list[dict]:
    claims = Dataset().claims(split)
    chosen = [c for c in claims if c.claim_id in ids] if ids else claims[:n]
    out = []
    headers = {"X-Intake-Token": get_settings().intake_token}
    with httpx.Client(base_url=get_settings().api_url, timeout=60, headers=headers) as client:
        for claim in chosen:
            files = [("files", (d.path.name, d.path.read_bytes())) for d in claim.docs]
            resp = client.post("/api/claims", files=files, data={"scenario_id": claim.claim_id})
            resp.raise_for_status()
            out.append(resp.json())
    return out
