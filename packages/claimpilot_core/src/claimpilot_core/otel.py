"""Traces for the AWS deployment: OpenTelemetry spans to the ADOT sidecar, which forwards to X-Ray.

Langfuse stays the tracer for local runs. In AWS there is no Langfuse, and X-Ray is not a place for
prompts, so these spans carry the step, the model, the prompt version, token counts and latency,
and never message or response text, redacted or not. The claim id is an indexed attribute
(infra/adot/collector.yaml), which makes one claim's steps one X-Ray filter.

Trace ids follow X-Ray's format (the first 32 bits are the start time in epoch seconds) so the
collector's awsxray exporter accepts them.
"""

import contextlib
import random
import time
from collections.abc import Iterator
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.sdk.trace.id_generator import IdGenerator
from opentelemetry.trace import Span


class XRayIdGenerator(IdGenerator):
    def generate_span_id(self) -> int:
        return random.getrandbits(64)

    def generate_trace_id(self) -> int:
        return (int(time.time()) << 96) | random.getrandbits(96)


def xray_trace_id(span: Span) -> str:
    raw = format(span.get_span_context().trace_id, "032x")
    return f"1-{raw[:8]}-{raw[8:]}"


class OtelTracer:
    def __init__(self, endpoint: str, *, exporter: SpanExporter | None = None) -> None:
        if exporter is None:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
        # Resource.create reads OTEL_SERVICE_NAME, which the task definition sets per service.
        self.provider = TracerProvider(resource=Resource.create(), id_generator=XRayIdGenerator())
        self.provider.add_span_processor(BatchSpanProcessor(exporter))
        self.tracer = self.provider.get_tracer("claimpilot")

    @contextlib.contextmanager
    def step(self, claim_id: str, step: str, **metadata: Any) -> Iterator[str]:
        attributes = {"claimpilot.claim_id": claim_id, "claimpilot.step": step}
        attributes |= {f"claimpilot.{k}": str(v) for k, v in metadata.items() if v is not None}
        with self.tracer.start_as_current_span(f"step:{step}", attributes=attributes) as span:
            yield xray_trace_id(span)

    @contextlib.contextmanager
    def generation(self, *, name: str, model: str, prompt: str | None) -> Iterator["_Generation"]:
        provider, _, model_id = model.partition(":")
        attributes = {
            "gen_ai.system": provider,
            "gen_ai.request.model": model_id or provider,
            "claimpilot.prompt": prompt or "",
        }
        with self.tracer.start_as_current_span(name, attributes=attributes) as span:
            yield _Generation(span)

    def flush(self) -> None:
        self.provider.force_flush()


class _Generation:
    """Takes what Langfuse's generation takes; keeps the numbers and drops the text."""

    def __init__(self, span: Span) -> None:
        self.span = span

    def update(
        self,
        *,
        usage_details: dict[str, int] | None = None,
        metadata: dict[str, Any] | None = None,
        **_ignored: Any,  # output: response text stays out of traces
    ) -> None:
        if usage_details:
            self.span.set_attribute("gen_ai.usage.input_tokens", int(usage_details.get("input", 0)))
            self.span.set_attribute(
                "gen_ai.usage.output_tokens", int(usage_details.get("output", 0))
            )
        for key in ("cached", "latency_ms"):
            if metadata and metadata.get(key) is not None:
                self.span.set_attribute(f"claimpilot.{key}", metadata[key])
