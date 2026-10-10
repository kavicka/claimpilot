"""Recorded model responses ("cassettes") for deterministic CI runs.

A cassette key is the hash of provider, model, think flag, prompt hash and the exact request
messages and schema. A changed prompt therefore has no recording: in replay mode that raises
`CassetteMissingError`, and the eval runner marks the suite stale instead of passing silently.
"""

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any

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


IMAGE_REF = "sha256:"


def image_digest(image: str) -> str:
    """Images are keyed by their hash. An eval run without the page files (CI) passes
    "sha256:<hex>" references from the committed page index instead of the images."""
    if image.startswith(IMAGE_REF):
        return image[len(IMAGE_REF) :]
    return hashlib.sha256(image.encode()).hexdigest()


def _message(m: Any) -> dict[str, Any]:
    out = {k: v for k, v in m.model_dump().items() if k not in ("tool_calls", "tool_name") or v}
    if out.get("images"):
        out["images"] = [image_digest(i) for i in out["images"]]
    return out


def cassette_key(req: LLMRequest, tools: list[dict] | None = None) -> str:
    tools_key = [t.get("function", {}).get("name") for t in tools] if tools else None
    material = {
        "provider": req.spec.provider,
        "model": req.spec.model,
        "think": req.spec.think,
        "prompt_hash": req.prompt_hash,
        # Tool fields only when used, so keys of plain requests did not change when they were added.
        "messages": [_message(m) for m in req.messages],
        "schema": req.json_schema,
    }
    if tools_key:  # only tool-calling requests carry it, so other keys stay stable
        material["tools"] = tools_key
    blob = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


class CassetteStore:
    def __init__(self, root: Path, mode: CassetteMode) -> None:
        self.root = root
        self.mode = mode

    def _path(self, req: LLMRequest, key: str) -> Path:
        return self.root / req.step / f"{key[:2]}" / f"{key}.json"

    def load(self, req: LLMRequest, tools: list[dict] | None = None) -> LLMResponse | None:
        if self.mode not in (CassetteMode.REPLAY, CassetteMode.AUTO):
            return None
        key = cassette_key(req, tools)
        path = self._path(req, key)
        if not path.exists():
            if any(i.startswith(IMAGE_REF) for m in req.messages for i in m.images):
                raise CassetteMissingError(key, req)  # no page files here, nothing to send
            if self.mode is CassetteMode.AUTO:
                return None
            raise CassetteMissingError(key, req)
        data = json.loads(path.read_text(encoding="utf-8"))
        response = LLMResponse.model_validate(data["response"])
        response.cached = True
        return response

    def save(self, req: LLMRequest, response: LLMResponse, tools: list[dict] | None = None) -> None:
        if self.mode not in (CassetteMode.RECORD, CassetteMode.AUTO):
            return
        key = cassette_key(req, tools)
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
