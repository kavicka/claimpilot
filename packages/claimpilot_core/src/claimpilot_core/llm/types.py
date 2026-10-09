from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    images: list[str] = Field(default_factory=list)  # base64 PNG/JPEG, local models only


class ModelSpec(BaseModel):
    """Which model runs a pipeline step, set per step in config/providers.yaml."""

    provider: Literal["ollama"] = "ollama"
    model: str
    think: bool = False
    temperature: float = 0.0
    num_ctx: int = 16384
    seed: int = 7

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


class LLMRequest(BaseModel):
    step: str
    spec: ModelSpec
    messages: list[ChatMessage]
    json_schema: dict[str, Any] | None = None
    prompt_id: str | None = None
    prompt_hash: str | None = None


class Usage(BaseModel):
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


class LLMResponse(BaseModel):
    text: str
    thinking: str | None = None
    model: str
    provider: str
    usage: Usage = Field(default_factory=Usage)
    cached: bool = False
