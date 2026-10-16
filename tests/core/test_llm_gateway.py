import json

import httpx
import pytest
import respx
from pydantic import BaseModel

from claimpilot_core.llm.cassette import CassetteMissingError, CassetteMode, cassette_key
from claimpilot_core.llm.gateway import LLMGateway, OutputValidationError, collect_calls
from claimpilot_core.llm.prompts import PromptFormatError, parse_prompt

PROMPT = """---
version: 3
---
## system
You extract {{ what }}.

## user
Document:
{{ text }}
"""


class Out(BaseModel):
    total: float
    currency: str


def ollama_reply(content: str, tokens_in: int = 11, tokens_out: int = 5) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "qwen3:14b",
            "message": {"role": "assistant", "content": content},
            "prompt_eval_count": tokens_in,
            "eval_count": tokens_out,
        },
    )


@pytest.fixture
def prompts_dir(tmp_settings):
    d = tmp_settings.cassettes_dir.parent / "prompts"
    (d / "extraction").mkdir(parents=True)
    (d / "extraction" / "invoice.md").write_text(PROMPT)
    tmp_settings.prompts_dir = d
    return d


def test_parse_prompt_reads_version_sections_and_hash():
    p = parse_prompt("extraction/invoice", PROMPT)
    assert p.version == "3"
    assert p.system == "You extract {{ what }}."
    assert p.user.startswith("Document:")
    assert len(p.sha) == 64
    assert p.tag == f"extraction/invoice@3+{p.sha[:8]}"
    msgs = p.render(what="totals", text="Total 12,50 EUR")
    assert [m.role for m in msgs] == ["system", "user"]
    assert "Total 12,50 EUR" in msgs[1].content


def test_prompt_without_version_is_rejected():
    with pytest.raises(PromptFormatError):
        parse_prompt("x/y", "---\nfoo: 1\n---\n## user\nhi")


def test_prompt_without_user_section_is_rejected():
    with pytest.raises(PromptFormatError):
        parse_prompt("x/y", "---\nversion: 1\n---\n## system\nhi")


@respx.mock
async def test_generate_json_sends_schema_and_think_false(tmp_settings, prompts_dir):
    route = respx.post("http://ollama.test/api/chat").mock(
        return_value=ollama_reply('{"total": 12.5, "currency": "EUR"}')
    )
    gw = LLMGateway(tmp_settings)
    with collect_calls() as calls:
        gen = await gw.generate_json(
            "extraction", "extraction/invoice", Out, {"what": "totals", "text": "12,50 EUR"}
        )
    assert gen.value == Out(total=12.5, currency="EUR")
    sent = json.loads(route.calls[0].request.content)
    assert sent["think"] is False
    assert sent["format"]["properties"]["total"]["type"] == "number"
    assert sent["options"]["temperature"] == 0.0
    assert calls[0].tokens_in == 11
    assert calls[0].step == "extraction"
    assert (gen.prompt_tag or "").startswith("extraction/invoice@3+")


@respx.mock
async def test_invalid_json_is_retried_with_the_validation_error(tmp_settings, prompts_dir):
    route = respx.post("http://ollama.test/api/chat").mock(
        side_effect=[
            ollama_reply('{"total": "twelve"}'),
            ollama_reply('{"total": 12.5, "currency": "EUR"}'),
        ]
    )
    gw = LLMGateway(tmp_settings)
    gen = await gw.generate_json(
        "extraction", "extraction/invoice", Out, {"what": "x", "text": "y"}
    )
    assert gen.attempts == 2
    retry_messages = json.loads(route.calls[1].request.content)["messages"]
    assert "failed validation" in retry_messages[-1]["content"]


@respx.mock
async def test_gives_up_after_max_attempts(tmp_settings, prompts_dir):
    respx.post("http://ollama.test/api/chat").mock(return_value=ollama_reply("not json"))
    gw = LLMGateway(tmp_settings)
    with pytest.raises(OutputValidationError):
        await gw.generate_json("extraction", "extraction/invoice", Out, {"what": "x", "text": "y"})


@respx.mock
async def test_record_then_replay_without_network(tmp_settings, prompts_dir):
    respx.post("http://ollama.test/api/chat").mock(
        return_value=ollama_reply('{"total": 1, "currency": "CZK"}')
    )
    variables = {"what": "x", "text": "y"}
    rec = LLMGateway(tmp_settings, cassette_mode=CassetteMode.RECORD)
    await rec.generate_json("extraction", "extraction/invoice", Out, variables)
    assert any(tmp_settings.cassettes_dir.rglob("*.json"))

    respx.reset()
    blocked = respx.post("http://ollama.test/api/chat").mock(side_effect=AssertionError)
    rep = LLMGateway(tmp_settings, cassette_mode=CassetteMode.REPLAY)
    gen = await rep.generate_json("extraction", "extraction/invoice", Out, variables)
    assert gen.value.currency == "CZK"
    assert gen.response.cached
    assert not blocked.called


@respx.mock
async def test_changed_prompt_has_no_cassette_in_replay(tmp_settings, prompts_dir):
    respx.post("http://ollama.test/api/chat").mock(
        return_value=ollama_reply('{"total": 1, "currency": "CZK"}')
    )
    variables = {"what": "x", "text": "y"}
    await LLMGateway(tmp_settings, cassette_mode=CassetteMode.RECORD).generate_json(
        "extraction", "extraction/invoice", Out, variables
    )
    (prompts_dir / "extraction" / "invoice.md").write_text(
        PROMPT.replace("version: 3", "version: 4")
    )
    rep = LLMGateway(tmp_settings, cassette_mode=CassetteMode.REPLAY)
    with pytest.raises(CassetteMissingError):
        await rep.generate_json("extraction", "extraction/invoice", Out, variables)


@respx.mock
async def test_answer_in_thinking_field_is_used_when_thinking_is_off(tmp_settings, prompts_dir):
    respx.post("http://ollama.test/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "qwen3-vl:8b",
                "message": {"content": "", "thinking": '{"total": 2, "currency": "EUR"}'},
            },
        )
    )
    gen = await LLMGateway(tmp_settings).generate_json(
        "extraction", "extraction/invoice", Out, {"what": "x", "text": "y"}
    )
    assert gen.value.total == 2
    assert gen.response.thinking is None


def test_spec_for_uses_step_config_and_overrides(tmp_settings):
    gw = LLMGateway(tmp_settings)
    assert gw.spec_for("routing").model == "qwen3:14b"
    assert gw.spec_for("extraction").think is False
    over = LLMGateway(tmp_settings, overrides={"extraction": "gemma3:12b"})
    assert over.spec_for("extraction").model == "gemma3:12b"
    assert over.spec_for("routing").model == "qwen3:14b"
    with pytest.raises(KeyError):
        gw.spec_for("nope")


def test_cassette_key_changes_with_model():
    from claimpilot_core.llm.types import ChatMessage, LLMRequest, ModelSpec

    base = LLMRequest(
        step="s", spec=ModelSpec(model="a"), messages=[ChatMessage(role="user", content="hi")]
    )
    other = base.model_copy(update={"spec": ModelSpec(model="b")})
    assert cassette_key(base) != cassette_key(other)


def test_an_image_and_its_hash_reference_share_a_cassette_key():
    from claimpilot_core.llm.cassette import IMAGE_REF, cassette_key, image_digest
    from claimpilot_core.llm.types import ChatMessage, LLMRequest, ModelSpec

    def req(image: str) -> LLMRequest:
        return LLMRequest(
            step="extraction_vision",
            spec=ModelSpec(model="qwen3-vl:8b"),
            messages=[ChatMessage(role="user", content="read", images=[image])],
        )

    image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    assert cassette_key(req(image)) == cassette_key(req(IMAGE_REF + image_digest(image)))
    assert cassette_key(req(image)) != cassette_key(req(image + "AA"))


async def test_cloud_steps_go_to_bedrock_and_keep_their_own_cassettes(tmp_settings):
    """With the cloud model map the gateway sends Claude steps to the Bedrock client, records
    them under the bedrock key, and replays them without a call."""
    from types import SimpleNamespace

    from claimpilot_core.llm.bedrock import BedrockClaudeClient

    class Messages:
        calls = 0

        async def create(self, **params):
            Messages.calls += 1
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"answer": "yes"}')],
                stop_reason="end_turn",
                model=params["model"],
                usage=SimpleNamespace(input_tokens=10, output_tokens=3),
            )

    class Out(BaseModel):
        answer: str

    settings = tmp_settings.model_copy(update={"providers_file": "providers.cloud.yaml"})
    for mode in (CassetteMode.RECORD, CassetteMode.REPLAY):
        gw = LLMGateway(settings, cassette_mode=mode)
        gw._bedrock = BedrockClaudeClient(
            "eu-central-1", client=SimpleNamespace(messages=Messages())
        )
        gen = await gw.generate_json("smoke", "smoke/invoice_json", Out, {"text": "Is it?"})
        assert gen.value.answer == "yes"
        assert gen.spec.key == "bedrock:eu.anthropic.claude-haiku-5-5"
    assert Messages.calls == 1  # the second run replayed
    assert list((settings.cassettes_dir / "smoke").rglob("*.json"))


def test_a_sampled_repeat_has_its_own_cassette_and_sampling(tmp_settings):
    """Variance runs (adversarial repeats): sample n sets temperature and seed and gets its own
    cassette key; without a sample, specs and keys stay as they were."""
    from claimpilot_core.llm.types import ChatMessage, LLMRequest

    plain = LLMGateway(tmp_settings).spec_for("extraction")
    sampled = LLMGateway(tmp_settings, sample=3).spec_for("extraction")
    assert plain.sample is None and (plain.temperature, plain.seed) == (0.0, 7)
    assert sampled.sample == 3 and sampled.temperature == 0.7 and sampled.seed == 7 + 3

    def req(spec):
        return LLMRequest(
            step="extraction", spec=spec, messages=[ChatMessage(role="user", content="x")]
        )

    assert cassette_key(req(plain)) != cassette_key(req(sampled))
    assert cassette_key(req(plain)) == cassette_key(req(plain.model_copy(update={"seed": 99})))
