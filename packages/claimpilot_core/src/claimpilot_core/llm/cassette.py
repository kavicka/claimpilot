"""Recorded model responses ("cassettes") for deterministic CI runs.

A cassette key is the hash of provider, model, think flag, prompt hash and the exact request
messages and schema. A changed prompt therefore has no recording: in replay mode that raises
`CassetteMissingError`, and the eval runner marks the suite stale instead of passing silently.
"""

import hashlib
import json
from enum import StrEnum
from pathlib import Path

from claimpilot_core.llm.types import LLMRequest, LLMResponse


class CassetteMode(StrEnum):
    OFF = "off"
    RECORD = "record"
    REPLAY = "replay"
    AUTO = "auto"  # replay when recorded, otherwise call the model and record


class CassetteMissingError(LookupError):
    def __init__(self, key: str, request: LLMRequest) -> None:
        super().__init__(
            f"no cassette for step={request.step} prompt={request.prompt_id} "
            f"hash={(request.prompt_hash or '')[:8]} key={key[:12]}"
        )
        self.key = key
        self.request = request


def cassette_key(req: LLMRequest) -> str:
    material = {
        "provider": req.spec.provider,
        "model": req.spec.model,
        "think": req.spec.think,
        "prompt_hash": req.prompt_hash,
        "messages": [m.model_dump() for m in req.messages],
        "schema": req.json_schema,
    }
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


class CassetteStore:
    def __init__(self, root: Path, mode: CassetteMode) -> None:
        self.root = root
        self.mode = mode

    def _path(self, req: LLMRequest, key: str) -> Path:
        return self.root / req.step / f"{key[:2]}" / f"{key}.json"

    def load(self, req: LLMRequest) -> LLMResponse | None:
        if self.mode not in (CassetteMode.REPLAY, CassetteMode.AUTO):
            return None
        key = cassette_key(req)
        path = self._path(req, key)
        if not path.exists():
            if self.mode is CassetteMode.AUTO:
                return None
            raise CassetteMissingError(key, req)
        data = json.loads(path.read_text(encoding="utf-8"))
        response = LLMResponse.model_validate(data["response"])
        response.cached = True
        return response

    def save(self, req: LLMRequest, response: LLMResponse) -> None:
        if self.mode not in (CassetteMode.RECORD, CassetteMode.AUTO):
            return
        key = cassette_key(req)
        path = self._path(req, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "step": req.step,
            "prompt_id": req.prompt_id,
            "prompt_hash": req.prompt_hash,
            "model": req.spec.key,
            "response": response.model_dump(),
        }
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
