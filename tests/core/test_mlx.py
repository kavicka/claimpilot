"""The MLX provider: a local LoRA adapter served by mlx_lm.server (ADR-014)."""

import json

import httpx
import respx
from pydantic import BaseModel

from claimpilot_core.llm.cassette import cassette_key
from claimpilot_core.llm.gateway import LLMGateway
from claimpilot_core.llm.types import ChatMessage, LLMRequest, ModelSpec

BASE = "mlx-community/Qwen3-8B-4bit"


class Out(BaseModel):
    total: str


def mlx_reply(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": BASE,
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 7},
        },
    )


def test_an_override_names_provider_base_and_adapter(tmp_settings):
    gw = LLMGateway(tmp_settings, overrides={"invoice_lines": f"mlx:{BASE}+invoice-v1"})
    spec = gw.spec_for("invoice_lines")
    assert (spec.provider, spec.model, spec.adapter) == ("mlx", BASE, "invoice-v1")
    assert spec.key == f"mlx:{BASE}+invoice-v1"
    # An Ollama model name keeps its colon.
    assert LLMGateway(tmp_settings, overrides={"smoke": "qwen3:14b"}).spec_for("smoke").model == (
        "qwen3:14b"
    )


def test_the_adapter_is_part_of_the_cassette_key_only_when_set():
    msgs = [ChatMessage(role="user", content="x")]
    plain = LLMRequest(step="s", spec=ModelSpec(provider="mlx", model=BASE), messages=msgs)
    tuned = plain.model_copy(update={"spec": ModelSpec(provider="mlx", model=BASE, adapter="a1")})
    other = plain.model_copy(update={"spec": ModelSpec(provider="mlx", model=BASE, adapter="a2")})
    assert len({cassette_key(plain), cassette_key(tuned), cassette_key(other)}) == 3


@respx.mock
async def test_a_call_goes_to_the_server_with_the_adapter_and_thinking_off(tmp_settings):
    tmp_settings.mlx_url = "http://mlx.test"
    route = respx.post("http://mlx.test/v1/chat/completions").mock(
        return_value=mlx_reply('<think>\n\n</think>\n\n```json\n{"total": "12,50"}\n```')
    )
    gw = LLMGateway(tmp_settings, overrides={"smoke": f"mlx:{BASE}+invoice-v1"})
    req = LLMRequest(
        step="smoke",
        spec=gw.spec_for("smoke"),
        messages=[ChatMessage(role="user", content="Total?")],
        json_schema=Out.model_json_schema(),
    )
    response = await gw.complete(req)
    assert Out.model_validate_json(response.text) == Out(total="12,50")
    assert (response.usage.tokens_in, response.usage.tokens_out) == (40, 7)
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == BASE
    assert sent["adapters"] == str(tmp_settings.adapters_dir / "invoice-v1")
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}
    assert sent["temperature"] == 0.0 and sent["seed"] == 7
