from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    # base64 PNG/JPEG: unmasked only to local models; masked (personal data blacked out) to a cloud
    images: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(
        default_factory=list
    )  # assistant turns that call tools
    tool_name: str | None = None  # tool result turns


class ModelSpec(BaseModel):
    """Which model runs a pipeline step, set per step in config/providers.yaml."""

    provider: Literal["ollama", "bedrock", "mlx"] = "ollama"
    model: str
    # MLX only: a LoRA adapter (a directory under settings.adapters_dir) on top of the base model.
    adapter: str | None = None
    think: bool = False
    temperature: float = 0.0
    num_ctx: int = 16384
    seed: int = 7
    # Cap on generated tokens, so a model caught in a repetition loop ends instead of running into
    # the client timeout. Not part of the cassette key.
    num_predict: int | None = None
    # Claude only: reasoning effort (low / medium / high); thinking off maps to "low".
    effort: str | None = None
    # Claude only: the model that answers when this one declines (stop_reason "refusal").
    fallback_model: str | None = None
    # Repeat n of a variance run (adversarial repeats): sampled, own seed, own cassette.
    sample: int | None = None

    @property
    def key(self) -> str:
        adapter = f"+{self.adapter}" if self.adapter else ""
        return f"{self.provider}:{self.model}{adapter}"


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
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    model: str
    provider: str
    usage: Usage = Field(default_factory=Usage)
    cached: bool = False
