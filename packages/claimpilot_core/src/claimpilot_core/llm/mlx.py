"""MLX adapter: a local LoRA adapter on its base model, served by `mlx_lm.server` (ADR-014).

The server speaks the OpenAI chat API and picks the adapter per request. It has no schema-
constrained decoding, so the reply is parsed as the model wrote it: a Qwen3 think block and a
code fence around the JSON are taken off. Thinking is off unless the step turns it on.
"""

import re
import time
from pathlib import Path
from typing import Any

import httpx

from claimpilot_core.llm.types import LLMRequest, LLMResponse, Usage

THINK = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)
FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class MlxError(RuntimeError):
    pass


def clean_reply(text: str) -> str:
    text = THINK.sub("", text)
    if m := FENCE.match(text):
        text = m[1]
    return text.strip()


class MlxClient:
    provider = "mlx"

    def __init__(self, base_url: str, adapters_dir: Path, *, timeout: float = 900.0) -> None:
        self.adapters_dir = adapters_dir
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    def chat_payload(self, req: LLMRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": req.spec.model,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "temperature": req.spec.temperature,
            "seed": req.spec.seed,
            "max_tokens": req.spec.num_predict or 8192,
            "chat_template_kwargs": {"enable_thinking": req.spec.think},
        }
        if req.spec.adapter:
            payload["adapters"] = str(self.adapters_dir / req.spec.adapter)
        return payload

    async def chat(
        self, req: LLMRequest, *, tools: list[dict[str, Any]] | None = None
    ) -> tuple[LLMResponse, dict[str, Any]]:
        if tools:
            raise MlxError("the MLX provider serves extraction steps only, without tools")
        started = time.perf_counter()
        resp = await self._client.post("/v1/chat/completions", json=self.chat_payload(req))
        if resp.status_code != 200:
            raise MlxError(f"mlx {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        message = data["choices"][0]["message"]
        usage = data.get("usage", {})
        response = LLMResponse(
            text=clean_reply(message.get("content") or ""),
            model=data.get("model", req.spec.model),
            provider=self.provider,
            usage=Usage(
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
        )
        return response, message
