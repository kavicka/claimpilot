"""The one door every model call goes through.

The gateway picks the model per pipeline step from `config/providers.yaml`, renders a versioned
prompt, applies cassettes (record/replay) and records usage for the step that is running.
Callers never talk to a provider directly, which keeps PII redaction and tracing at one point.
"""

import contextlib
import json
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel, ValidationError

from claimpilot_core.llm.bedrock import BedrockClaudeClient, BedrockEmbedder
from claimpilot_core.llm.cassette import CassetteMode, CassetteStore
from claimpilot_core.llm.ollama import EventHook, OllamaClient
from claimpilot_core.llm.prompts import Prompt, load_prompt
from claimpilot_core.llm.types import ChatMessage, LLMRequest, LLMResponse, ModelSpec
from claimpilot_core.observability import get_tracer
from claimpilot_core.settings import Settings, get_settings

log = structlog.get_logger(__name__)


@dataclass
class CallRecord:
    step: str
    model: str
    prompt: str | None
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cached: bool


_calls: ContextVar[list[CallRecord] | None] = ContextVar("llm_calls", default=None)


@contextlib.contextmanager
def collect_calls() -> Iterator[list[CallRecord]]:
    """Collect every model call made inside the block (used per pipeline step and per eval)."""
    calls: list[CallRecord] = []
    token = _calls.set(calls)
    try:
        yield calls
    finally:
        _calls.reset(token)


@dataclass
class Generation[T]:
    value: T
    response: LLMResponse
    prompt: Prompt | None
    spec: ModelSpec
    attempts: int = 1
    errors: list[str] = field(default_factory=list)

    @property
    def prompt_tag(self) -> str | None:
        return self.prompt.tag if self.prompt else None


class OutputValidationError(ValueError):
    pass


def load_providers(config_dir: Path, name: str = "providers.yaml") -> dict[str, Any]:
    return yaml.safe_load((config_dir / name).read_text(encoding="utf-8"))


class LLMGateway:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        overrides: dict[str, str] | None = None,
        event_hooks: dict[str, list[EventHook]] | None = None,
        cassette_mode: CassetteMode | None = None,
        sample: int | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.sample = sample
        self.providers = load_providers(self.settings.config_dir, self.settings.providers_file)
        self.overrides = overrides or {}
        self.client = OllamaClient(self.settings.ollama_url, event_hooks=event_hooks)
        self._bedrock: BedrockClaudeClient | None = None
        self._embedder: BedrockEmbedder | None = None
        mode = cassette_mode or CassetteMode(self.settings.llm_cassette_mode)
        self.cassettes = CassetteStore(self.settings.cassettes_dir, mode)

    async def aclose(self) -> None:
        await self.client.aclose()
        if self._bedrock is not None:
            await self._bedrock.aclose()

    def _client_for(self, spec: ModelSpec) -> OllamaClient | BedrockClaudeClient:
        if spec.provider == "bedrock":
            if self._bedrock is None:
                region = self.providers.get("bedrock", {}).get("region", self.settings.aws_region)
                self._bedrock = BedrockClaudeClient(region)
            return self._bedrock
        return self.client

    def spec_for(self, step: str) -> ModelSpec:
        defaults = self.providers.get("defaults", {})
        step_cfg = self.providers["steps"].get(step)
        if step_cfg is None:
            raise KeyError(f"no model configured for step '{step}' in providers.yaml")
        merged = {**defaults, **step_cfg}
        if step in self.overrides or "*" in self.overrides:
            merged["model"] = self.overrides.get(step, self.overrides.get("*"))
        if self.sample is not None:  # a variance run: sampled answers, one seed per repeat
            merged["temperature"] = max(float(merged.get("temperature", 0.0)), 0.7)
            merged["seed"] = int(merged.get("seed", 7)) + self.sample
            merged["sample"] = self.sample
        return ModelSpec.model_validate(merged)

    @property
    def embedding_model(self) -> str:
        return self.providers["embeddings"]["model"]

    async def complete(
        self, req: LLMRequest, *, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        with get_tracer().generation(
            name=f"llm:{req.step}",
            model=req.spec.key,
            prompt=req.prompt_id and f"{req.prompt_id}@{(req.prompt_hash or '')[:8]}",
            messages=[m.model_dump() for m in req.messages],
        ) as gen:
            cached = self.cassettes.load(req, tools)
            if cached is not None:
                response = cached
            else:
                response, _ = await self._client_for(req.spec).chat(req, tools=tools)
                self.cassettes.save(req, response, tools)
            gen.update(
                output=response.text or response.tool_calls,
                usage_details={
                    "input": response.usage.tokens_in,
                    "output": response.usage.tokens_out,
                },
                metadata={"cached": response.cached, "latency_ms": response.usage.latency_ms},
            )
        calls = _calls.get()
        if calls is not None:
            calls.append(
                CallRecord(
                    step=req.step,
                    model=req.spec.key,
                    prompt=req.prompt_id,
                    tokens_in=response.usage.tokens_in,
                    tokens_out=response.usage.tokens_out,
                    latency_ms=response.usage.latency_ms,
                    cached=response.cached,
                )
            )
        log.debug(
            "llm.call",
            step=req.step,
            model=req.spec.key,
            prompt=req.prompt_id,
            tokens_in=response.usage.tokens_in,
            tokens_out=response.usage.tokens_out,
            latency_ms=response.usage.latency_ms,
            cached=response.cached,
        )
        return response

    def _request(
        self,
        step: str,
        prompt: Prompt,
        variables: dict[str, Any],
        *,
        schema: dict[str, Any] | None,
        images: list[str] | None,
        spec: ModelSpec | None,
    ) -> LLMRequest:
        messages = prompt.render(**variables)
        if images:
            last = messages[-1]
            messages[-1] = ChatMessage(role=last.role, content=last.content, images=images)
        return LLMRequest(
            step=step,
            spec=spec or self.spec_for(step),
            messages=messages,
            json_schema=schema,
            prompt_id=prompt.prompt_id,
            prompt_hash=prompt.sha,
        )

    async def generate_json[T: BaseModel](
        self,
        step: str,
        prompt_id: str,
        output: type[T],
        variables: dict[str, Any],
        *,
        images: list[str] | None = None,
        spec: ModelSpec | None = None,
        max_attempts: int = 2,
    ) -> Generation[T]:
        """Schema-constrained call. A reply that fails validation is retried once with the error."""
        prompt = load_prompt(prompt_id, self.settings.prompts_dir)
        schema = output.model_json_schema()
        req = self._request(step, prompt, variables, schema=schema, images=images, spec=spec)
        errors: list[str] = []
        for attempt in range(1, max_attempts + 1):
            response = await self.complete(req)
            try:
                value = output.model_validate_json(response.text)
            except ValidationError as exc:
                errors.append(str(exc)[:1000])
                req = req.model_copy(
                    update={
                        "messages": [
                            *req.messages,
                            ChatMessage(role="assistant", content=response.text),
                            ChatMessage(
                                role="user",
                                content="The JSON above failed validation:\n"
                                f"{str(exc)[:800]}\nReturn corrected JSON only.",
                            ),
                        ]
                    }
                )
                continue
            return Generation(value, response, prompt, req.spec, attempt, errors)
        raise OutputValidationError(f"{prompt_id}: invalid JSON after {max_attempts} attempts")

    async def generate_text(
        self,
        step: str,
        prompt_id: str,
        variables: dict[str, Any],
        *,
        spec: ModelSpec | None = None,
    ) -> Generation[str]:
        prompt = load_prompt(prompt_id, self.settings.prompts_dir)
        req = self._request(step, prompt, variables, schema=None, images=None, spec=spec)
        response = await self.complete(req)
        return Generation(response.text.strip(), response, prompt, req.spec)

    async def _embed_batch(self, texts: list[str], kind: str) -> list[list[float]]:
        cfg = self.providers["embeddings"]
        if cfg.get("provider", "ollama") == "bedrock":
            if self._embedder is None:
                region = self.providers.get("bedrock", {}).get("region", self.settings.aws_region)
                self._embedder = BedrockEmbedder(cfg["model"], region)
            return await self._embedder.embed(texts, kind=kind)
        return await self.client.embed(cfg["model"], texts)

    async def embed(
        self, texts: list[str], *, batch: int = 32, kind: str = "document"
    ) -> list[list[float]]:
        """Embeddings, cached per text like cassettes so retrieval evals replay without a model.
        `kind` is "document" or "query" (Cohere embeds them differently; Ollama ignores it)."""
        import hashlib

        model = self.embedding_model
        folder = self.settings.cassettes_dir / "embeddings" / model.replace(":", "_")
        mode = self.cassettes.mode
        out: list[list[float] | None] = [None] * len(texts)
        todo: list[int] = []
        for i, text in enumerate(texts):
            path = folder / f"{hashlib.sha256(text.encode()).hexdigest()[:32]}.json"
            if mode in (CassetteMode.REPLAY, CassetteMode.AUTO) and path.exists():
                out[i] = json.loads(path.read_text("utf-8"))
            elif mode is CassetteMode.REPLAY:
                raise LookupError(f"no embedding cassette for {text[:60]!r}")
            else:
                todo.append(i)
        for start in range(0, len(todo), batch):
            idx = todo[start : start + batch]
            vectors = await self._embed_batch([texts[i] for i in idx], kind)
            for i, vec in zip(idx, vectors, strict=True):
                out[i] = vec
                if mode in (CassetteMode.RECORD, CassetteMode.AUTO):
                    path = folder / f"{hashlib.sha256(texts[i].encode()).hexdigest()[:32]}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps([round(x, 6) for x in vec]), "utf-8")
        return [v for v in out if v is not None]


def dumps(value: Any) -> str:
    """JSON for prompt variables: stable key order, readable non-ASCII."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, indent=1)
