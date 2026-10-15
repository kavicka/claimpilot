"""Claude on Amazon Bedrock (Phase 2), through the Anthropic SDK's Bedrock client.

The client calls `bedrock-runtime` (InvokeModel, SigV4) with the EU inference profiles
(`eu.anthropic.claude-*`). In eu-central-1 the 5.5 models are documented only through that
endpoint and profile; requests stay in the six EU Regions the profile routes to
(docs/research/aws-bedrock-facts.md, section 2). The Bedrock Mantle endpoint does not serve them
in Frankfurt.

The gateway hands this adapter the same `LLMRequest` it hands Ollama, so prompts, cassettes,
tracing and the PII guard stay where they are. Differences the adapter takes care of:

- JSON output uses structured outputs (`output_config.format`); the current Claude models reject
  a forced tool choice, and constrained decoding is what Ollama's `format` does locally.
- Sampling parameters (temperature, seed) are not sent: the 5.5 models reject non-default values.
  Determinism in evals comes from the cassettes, as it does locally.
- "Thinking off" in providers.yaml maps to effort `low`.
- A policy decline (`stop_reason: "refusal"`) is retried once on the step's `fallback_model`;
  without one, or if that declines too, `ModelRefusalError` sends the claim to a handler.
- Images are sent only when the caller says they are masked (see `extract_document_vision`).

Embeddings go through boto3 (`bedrock-runtime` InvokeModel), since they are not a Claude model.
"""

import asyncio
import base64
import copy
import json
import time
from typing import Any

from claimpilot_core.llm.types import ChatMessage, LLMRequest, LLMResponse, Usage

DEFAULT_MAX_TOKENS = 16000


class ModelRefusalError(RuntimeError):
    """The model (and its fallback) declined the request on policy grounds."""

    def __init__(self, model: str, category: str | None) -> None:
        super().__init__(f"{model} declined the request (category: {category or 'unknown'})")
        self.model, self.category = model, category


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Structured outputs want every object closed (`additionalProperties: false`)."""
    out = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node.setdefault("additionalProperties", False)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(out)
    return out


def _media_type(image_b64: str) -> str:
    head = base64.b64decode(image_b64[:16] + "=" * (-len(image_b64[:16]) % 4))
    return "image/jpeg" if head.startswith(b"\xff\xd8") else "image/png"


def _tool_use_id(call: dict[str, Any], n: int) -> str:
    return str(call.get("id") or f"call_{n}")


def to_messages(messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, Any]]]:
    """Gateway messages to the Messages API shape: system text apart, tool calls as `tool_use`
    blocks, consecutive tool results as `tool_result` blocks in one user turn (parallel calls
    must be answered together)."""
    system = "\n\n".join(m.content for m in messages if m.role == "system") or None
    out: list[dict[str, Any]] = []
    pending: list[str] = []  # tool_use ids waiting for their results, in call order
    n = 0
    for m in messages:
        if m.role == "system":
            continue
        if m.role == "tool":
            tool_id = pending.pop(0) if pending else f"call_{n}"
            block = {"type": "tool_result", "tool_use_id": tool_id, "content": m.content}
            if out and out[-1]["role"] == "user" and _only_tool_results(out[-1]):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue
        content: list[dict[str, Any]] = []
        for image in m.images:
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": _media_type(image), "data": image},
                }
            )
        if m.content:
            content.append({"type": "text", "text": m.content})
        if m.role == "assistant":
            for call in m.tool_calls:
                fn = call.get("function", {})
                args = fn.get("arguments") or {}
                tool_id = _tool_use_id(call, n)
                n += 1
                pending.append(tool_id)
                content.append(
                    {
                        "type": "tool_use",
                        "id": tool_id,
                        "name": fn.get("name"),
                        "input": json.loads(args) if isinstance(args, str) else args,
                    }
                )
        out.append({"role": m.role, "content": content or [{"type": "text", "text": ""}]})
    return system, out


def _only_tool_results(message: dict[str, Any]) -> bool:
    return all(b.get("type") == "tool_result" for b in message["content"])


def to_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """The gateway's (Ollama/OpenAI style) function tools as Messages API tools."""
    if not tools:
        return None
    out = []
    for tool in tools:
        fn = tool.get("function", tool)
        out.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return out


def request_params(
    req: LLMRequest, tools: list[dict[str, Any]] | None = None, *, model: str | None = None
) -> dict[str, Any]:
    system, messages = to_messages(req.messages)
    output_config: dict[str, Any] = {
        "effort": req.spec.effort or ("medium" if req.spec.think else "low")
    }
    if req.json_schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": strict_schema(req.json_schema)}
    params: dict[str, Any] = {
        "model": model or req.spec.model,
        "max_tokens": req.spec.num_predict or DEFAULT_MAX_TOKENS,
        "messages": messages,
        "output_config": output_config,
    }
    if system:
        params["system"] = system
    converted = to_tools(tools)
    if converted:
        params["tools"] = converted
    return params


class BedrockClaudeClient:
    provider = "bedrock"

    def __init__(self, region: str, *, client: Any = None) -> None:
        if client is None:
            import anthropic

            client = anthropic.AsyncAnthropicBedrock(aws_region=region)  # pyright: ignore[reportPrivateImportUsage]
        self._client = client

    async def aclose(self) -> None:
        await self._client.close()

    async def chat(
        self, req: LLMRequest, *, tools: list[dict[str, Any]] | None = None
    ) -> tuple[LLMResponse, dict[str, Any]]:
        started = time.perf_counter()
        message = await self._client.messages.create(**request_params(req, tools))
        if message.stop_reason == "refusal" and req.spec.fallback_model:
            message = await self._client.messages.create(
                **request_params(req, tools, model=req.spec.fallback_model)
            )
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            raise ModelRefusalError(message.model, getattr(details, "category", None))
        text = "".join(b.text for b in message.content if b.type == "text")
        tool_calls = [
            {"id": b.id, "function": {"name": b.name, "arguments": b.input}}
            for b in message.content
            if b.type == "tool_use"
        ]
        response = LLMResponse(
            text=text,
            tool_calls=tool_calls,
            model=message.model,
            provider=self.provider,
            usage=Usage(
                tokens_in=message.usage.input_tokens,
                tokens_out=message.usage.output_tokens,
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
        )
        return response, {"stop_reason": message.stop_reason}


class BedrockEmbedder:
    """Cohere Embed Multilingual v3 (1024 dimensions, the size of the pgvector column) through
    InvokeModel. Documents and queries are embedded with different input types."""

    def __init__(self, model: str, region: str, *, client: Any = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("bedrock-runtime", region_name=region)
        self.model, self._client = model, client

    async def embed(self, inputs: list[str], *, kind: str = "document") -> list[list[float]]:
        body = json.dumps(
            {
                "texts": inputs,
                "input_type": "search_query" if kind == "query" else "search_document",
                "truncate": "END",
            }
        )

        def call() -> dict[str, Any]:
            resp = self._client.invoke_model(modelId=self.model, body=body)
            return json.loads(resp["body"].read())

        data = await asyncio.to_thread(call)
        return data["embeddings"]
