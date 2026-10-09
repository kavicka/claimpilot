"""Ollama adapter over the native HTTP API.

Extraction-type calls pass a JSON schema as `format`, so Ollama constrains decoding to it;
that is more reliable on local models than tool calling. Thinking is off unless the step's
config turns it on.
"""

import time
from typing import Any

import httpx

from claimpilot_core.llm.types import ChatMessage, LLMRequest, LLMResponse, Usage

EventHook = Any  # httpx event hook callable


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    provider = "ollama"

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 600.0,
        event_hooks: dict[str, list[EventHook]] | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout, event_hooks=event_hooks or {}
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _message(m: ChatMessage) -> dict[str, Any]:
        out: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.images:
            out["images"] = m.images
        return out

    def chat_payload(self, req: LLMRequest, *, tools: list[dict[str, Any]] | None = None) -> dict:
        payload: dict[str, Any] = {
            "model": req.spec.model,
            "messages": [self._message(m) for m in req.messages],
            "stream": False,
            "think": req.spec.think,
            "options": {
                "temperature": req.spec.temperature,
                "seed": req.spec.seed,
                "num_ctx": req.spec.num_ctx,
            },
        }
        if req.json_schema is not None:
            payload["format"] = req.json_schema
        if tools:
            payload["tools"] = tools
        return payload

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._client.post("/api/chat", json=payload)
        if resp.status_code == 400 and "does not support thinking" in resp.text:
            # Instruct-only models reject the think flag even when it is false.
            payload = {k: v for k, v in payload.items() if k != "think"}
            resp = await self._client.post("/api/chat", json=payload)
        if resp.status_code != 200:
            raise OllamaError(f"ollama {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    async def chat(
        self, req: LLMRequest, *, tools: list[dict[str, Any]] | None = None
    ) -> tuple[LLMResponse, dict[str, Any]]:
        started = time.perf_counter()
        data = await self._post_chat(self.chat_payload(req, tools=tools))
        message = data.get("message", {})
        text, thinking = message.get("content", ""), message.get("thinking") or None
        if not text.strip() and thinking and not req.spec.think:
            # qwen3-vl with think=false returns its whole answer in the thinking field.
            text, thinking = thinking, None
        response = LLMResponse(
            text=text,
            thinking=thinking,
            model=data.get("model", req.spec.model),
            provider=self.provider,
            usage=Usage(
                tokens_in=data.get("prompt_eval_count", 0),
                tokens_out=data.get("eval_count", 0),
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
        )
        return response, message

    async def embed(self, model: str, inputs: list[str]) -> list[list[float]]:
        resp = await self._client.post("/api/embed", json={"model": model, "input": inputs})
        if resp.status_code != 200:
            raise OllamaError(f"ollama embed {resp.status_code}: {resp.text[:500]}")
        return resp.json()["embeddings"]

    async def list_models(self) -> list[str]:
        resp = await self._client.get("/api/tags")
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
