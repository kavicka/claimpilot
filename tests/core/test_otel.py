"""Spans for X-Ray: numbers and names only, never prompt or response text."""

import time

from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from claimpilot_core.otel import OtelTracer


def test_a_step_and_its_model_call_become_spans_without_any_text():
    exporter = InMemorySpanExporter()
    tracer = OtelTracer("http://127.0.0.1:4318", exporter=exporter)
    with (
        tracer.step("c-123", "extract", reference="CP-2026-000123"),
        tracer.generation(
            name="llm:extraction", model="bedrock:eu.anthropic.claude-sonnet-5-5", prompt="p@1"
        ) as gen,
    ):
        gen.update(
            output='{"patient": "Jana Kováčová"}',
            usage_details={"input": 2477, "output": 737},
            metadata={"cached": False, "latency_ms": 5120},
        )
    tracer.flush()
    step, call = sorted(exporter.get_finished_spans(), key=lambda s: s.name, reverse=True)
    assert step.name == "step:extract" and call.name == "llm:extraction"
    assert step.attributes == {
        "claimpilot.claim_id": "c-123",
        "claimpilot.step": "extract",
        "claimpilot.reference": "CP-2026-000123",
    }
    assert dict(call.attributes or {}) == {
        "gen_ai.system": "bedrock",
        "gen_ai.request.model": "eu.anthropic.claude-sonnet-5-5",
        "claimpilot.prompt": "p@1",
        "gen_ai.usage.input_tokens": 2477,
        "gen_ai.usage.output_tokens": 737,
        "claimpilot.cached": False,
        "claimpilot.latency_ms": 5120,
    }
    assert "Kováčová" not in str([s.to_json() for s in (step, call)])
    assert call.parent is not None and step.context is not None
    assert call.parent.span_id == step.context.span_id


def test_trace_ids_carry_the_start_time_as_x_ray_expects():
    exporter = InMemorySpanExporter()
    tracer = OtelTracer("http://127.0.0.1:4318", exporter=exporter)
    with tracer.step("c-1", "parse") as trace_id:
        pass
    version, epoch, rest = trace_id.split("-")
    assert version == "1" and len(rest) == 24
    assert abs(int(epoch, 16) - time.time()) < 5


def test_the_tracer_uses_otel_only_when_an_endpoint_is_set(monkeypatch):
    from claimpilot_core import observability
    from claimpilot_core.settings import get_settings

    aws = get_settings().model_copy(
        update={"otel_endpoint": "http://127.0.0.1:4318", "langfuse_host": ""}
    )
    monkeypatch.setattr(observability, "get_settings", lambda: aws)
    tracer = observability.Tracer()
    assert tracer.otel is not None and tracer.client is None and tracer.enabled
    local = aws.model_copy(update={"otel_endpoint": ""})
    monkeypatch.setattr(observability, "get_settings", lambda: local)
    assert not observability.Tracer().enabled
