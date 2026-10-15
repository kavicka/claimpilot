"""The Bedrock adapter without AWS: request shapes, tool loops, refusals, and the real Anthropic SDK
client against a mocked HTTP transport."""

import base64
import io
import json
from types import SimpleNamespace

import httpx2
import pytest
from PIL import Image

from claimpilot_core.llm.bedrock import (
    BedrockClaudeClient,
    BedrockEmbedder,
    ModelRefusalError,
    request_params,
    strict_schema,
    to_messages,
)
from claimpilot_core.llm.types import ChatMessage, LLMRequest, ModelSpec

SONNET = ModelSpec(provider="bedrock", model="eu.anthropic.claude-sonnet-5-5", num_predict=2048)


def image_b64(fmt: str) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, fmt)
    return base64.b64encode(buf.getvalue()).decode()


def req(messages, **kw) -> LLMRequest:
    return LLMRequest(step="extraction", spec=kw.pop("spec", SONNET), messages=messages, **kw)


def test_json_requests_use_structured_outputs_and_no_sampling_parameters():
    schema = {
        "type": "object",
        "properties": {"total": {"type": "string"}, "line": {"$ref": "#/$defs/Line"}},
        "$defs": {"Line": {"type": "object", "properties": {"amount": {"type": "string"}}}},
    }
    params = request_params(
        req(
            [
                ChatMessage(role="system", content="Extract fields."),
                ChatMessage(role="user", content="Totale 279,50"),
            ],
            json_schema=schema,
        )
    )
    assert params["system"] == "Extract fields."
    assert params["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Totale 279,50"}]}
    ]
    fmt = params["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert fmt["schema"]["$defs"]["Line"]["additionalProperties"] is False
    assert "additionalProperties" not in schema  # the caller's schema is left alone
    assert params["output_config"]["effort"] == "low"  # thinking off
    assert params["max_tokens"] == 2048
    assert not {"temperature", "seed", "top_p", "tool_choice"} & params.keys()


def test_effort_follows_the_step_config():
    spec = SONNET.model_copy(update={"think": True})
    assert (
        request_params(req([ChatMessage(role="user", content="x")], spec=spec))["output_config"][
            "effort"
        ]
        == "medium"
    )
    spec = SONNET.model_copy(update={"effort": "high"})
    assert (
        request_params(req([ChatMessage(role="user", content="x")], spec=spec))["output_config"][
            "effort"
        ]
        == "high"
    )


def test_images_go_first_with_their_media_type():
    _, messages = to_messages(
        [ChatMessage(role="user", content="Read it", images=[image_b64("PNG"), image_b64("JPEG")])]
    )
    blocks = messages[0]["content"]
    assert [b["type"] for b in blocks] == ["image", "image", "text"]
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert blocks[1]["source"]["media_type"] == "image/jpeg"


def test_a_tool_loop_becomes_tool_use_and_one_turn_of_tool_results():
    history = [
        ChatMessage(role="user", content="Fix the payload."),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                {
                    "id": "toolu_1",
                    "function": {"name": "get_code_list", "arguments": {"name": "country"}},
                },
                {"function": {"name": "get_code_list", "arguments": '{"name": "coverage"}'}},
            ],
        ),
        ChatMessage(role="tool", content='{"AT": "Austria"}', tool_name="get_code_list"),
        ChatMessage(role="tool", content='{"MED": "medical"}', tool_name="get_code_list"),
    ]
    _, messages = to_messages(history)
    uses = messages[1]["content"]
    assert [(b["type"], b["id"], b["input"]) for b in uses] == [
        ("tool_use", "toolu_1", {"name": "country"}),
        ("tool_use", "call_1", {"name": "coverage"}),
    ]
    assert len(messages) == 3  # both results in one user turn, as parallel calls require
    results = messages[2]["content"]
    assert [(b["tool_use_id"], b["content"]) for b in results] == [
        ("toolu_1", '{"AT": "Austria"}'),
        ("call_1", '{"MED": "medical"}'),
    ]


def test_function_tools_become_messages_api_tools():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "submit_claim",
                "description": "Send the payload",
                "parameters": {"type": "object", "properties": {"payload": {"type": "object"}}},
            },
        }
    ]
    params = request_params(req([ChatMessage(role="user", content="x")]), tools)
    assert params["tools"] == [
        {
            "name": "submit_claim",
            "description": "Send the payload",
            "input_schema": {"type": "object", "properties": {"payload": {"type": "object"}}},
        }
    ]


def test_strict_schema_closes_nested_objects_inside_lists():
    schema = {
        "type": "object",
        "properties": {"rows": {"type": "array", "items": {"type": "object", "properties": {}}}},
    }
    assert strict_schema(schema)["properties"]["rows"]["items"]["additionalProperties"] is False


def message(text="", *, stop="end_turn", tool=None, model="eu.anthropic.claude-sonnet-5-5"):
    content = []
    if text:
        content.append(SimpleNamespace(type="text", text=text))
    if tool:
        content.append(SimpleNamespace(type="tool_use", id="toolu_9", name=tool[0], input=tool[1]))
    return SimpleNamespace(
        content=content,
        stop_reason=stop,
        stop_details=SimpleNamespace(category="cyber") if stop == "refusal" else None,
        model=model,
        usage=SimpleNamespace(input_tokens=120, output_tokens=30),
    )


class FakeMessages:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def create(self, **params):
        self.calls.append(params)
        return self.replies.pop(0)


def fake_client(*replies):
    return SimpleNamespace(messages=FakeMessages(replies))


async def test_text_tool_calls_and_usage_come_back_in_the_gateway_shape():
    client = fake_client(message("ok", tool=("get_code_list", {"name": "country"})))
    response, _ = await BedrockClaudeClient("eu-central-1", client=client).chat(
        req([ChatMessage(role="user", content="x")])
    )
    assert (response.text, response.provider) == ("ok", "bedrock")
    assert response.tool_calls == [
        {"id": "toolu_9", "function": {"name": "get_code_list", "arguments": {"name": "country"}}}
    ]
    assert (response.usage.tokens_in, response.usage.tokens_out) == (120, 30)


async def test_a_refusal_is_retried_once_on_the_fallback_model():
    spec = SONNET.model_copy(update={"fallback_model": "eu.anthropic.claude-opus-5-5"})
    client = fake_client(
        message(stop="refusal"), message("{}", model="eu.anthropic.claude-opus-5-5")
    )
    response, _ = await BedrockClaudeClient("eu-central-1", client=client).chat(
        req([ChatMessage(role="user", content="x")], spec=spec)
    )
    assert [c["model"] for c in client.messages.calls] == [
        "eu.anthropic.claude-sonnet-5-5",
        "eu.anthropic.claude-opus-5-5",
    ]
    assert response.model == "eu.anthropic.claude-opus-5-5"


async def test_a_refusal_without_a_fallback_goes_to_a_handler():
    client = fake_client(message(stop="refusal"))
    with pytest.raises(ModelRefusalError) as info:
        await BedrockClaudeClient("eu-central-1", client=client).chat(
            req([ChatMessage(role="user", content="x")])
        )
    assert info.value.category == "cyber"


async def test_the_real_sdk_client_accepts_the_request_shape(monkeypatch):
    """Through the Anthropic SDK's Bedrock client, with HTTP mocked: checks that the parameters
    we build are ones the SDK sends to bedrock-runtime in Frankfurt, signed, and that its response
    parses back."""
    import anthropic

    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "eu.anthropic.claude-sonnet-5-5",
                "content": [{"type": "text", "text": '{"total": "279,50"}'}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 50, "output_tokens": 8},
            },
        )

    sdk = anthropic.AsyncAnthropicBedrock(
        aws_region="eu-central-1",
        aws_access_key="AKIDEXAMPLE",
        aws_secret_key="test-only",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    client = BedrockClaudeClient("eu-central-1", client=sdk)
    response, _ = await client.chat(
        req(
            [ChatMessage(role="user", content="Totale 279,50", images=[image_b64("PNG")])],
            json_schema={"type": "object", "properties": {"total": {"type": "string"}}},
        )
    )
    assert response.text == '{"total": "279,50"}'
    assert seen["url"] == (
        "https://bedrock-runtime.eu-central-1.amazonaws.com/model/eu.anthropic.claude-sonnet-5-5/invoke"
    )
    assert seen["auth"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "/eu-central-1/bedrock/aws4_request" in seen["auth"]
    body = seen["body"]
    assert "model" not in body and body["anthropic_version"].startswith("bedrock-")
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["messages"][0]["content"][0]["type"] == "image"
    await client.aclose()


class FakeBoto:
    def __init__(self):
        self.calls = []

    def invoke_model(self, modelId, body):  # noqa: N803 - boto3 keyword names
        self.calls.append((modelId, json.loads(body)))
        n = len(json.loads(body)["texts"])
        return {"body": io.BytesIO(json.dumps({"embeddings": [[0.1] * 1024] * n}).encode())}


async def test_embeddings_tell_documents_from_queries():
    boto = FakeBoto()
    embedder = BedrockEmbedder("cohere.embed-multilingual-v3", "eu-central-1", client=boto)
    docs = await embedder.embed(["čl. 4 ods. 1", "čl. 11 ods. 3"])
    query = await embedder.embed(["ošetrenie zubov"], kind="query")
    assert (len(docs), len(docs[0]), len(query)) == (2, 1024, 1)
    assert [c[1]["input_type"] for c in boto.calls] == ["search_document", "search_query"]
    assert boto.calls[0][0] == "cohere.embed-multilingual-v3"
