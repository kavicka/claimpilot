"""Tracing to self-hosted Langfuse (OpenTelemetry under the hood).

One trace per claim: the trace id is derived from the claim id, so steps that run as separate
arq jobs land in the same trace. Each pipeline step is a span; each model call is a generation
with model, prompt version, tokens and latency. Model inputs are already redacted; page images are
replaced by a count. With no Langfuse host configured, everything here is a no-op.
"""

import contextlib
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from claimpilot_core.settings import get_settings


class Tracer:
    def __init__(self) -> None:
        s = get_settings()
        self.client = None
        if s.langfuse_host and s.langfuse_public_key and s.langfuse_secret_key.get_secret_value():
            from langfuse import Langfuse

            self.client = Langfuse(
                public_key=s.langfuse_public_key,
                secret_key=s.langfuse_secret_key.get_secret_value(),
                host=s.langfuse_host,
                environment="local",
            )

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def trace_id(self, claim_id: str) -> str | None:
        if self.client is None:
            return None
        from langfuse import Langfuse

        return Langfuse.create_trace_id(seed=claim_id)

    @contextlib.contextmanager
    def step(self, claim_id: str, step: str, **metadata: Any) -> Iterator[str | None]:
        if self.client is None:
            yield None
            return
        trace_id = self.trace_id(claim_id)
        with self.client.start_as_current_observation(
            trace_context={"trace_id": trace_id},  # type: ignore[typeddict-item]
            name=f"step:{step}",
            as_type="span",
            metadata={"claim_id": claim_id, **metadata},
        ):
            yield trace_id

    @contextlib.contextmanager
    def generation(
        self, *, name: str, model: str, prompt: str | None, messages: list[dict[str, Any]]
    ) -> Iterator[Any]:
        """Wraps the model call, so the generation's latency is the call's own. The caller reports
        output and usage with `.update(...)` on what this yields (a no-op stub when disabled)."""
        if self.client is None:
            yield _NoGeneration()
            return
        safe = [
            {
                "role": m["role"],
                "content": m["content"],
                **({"images": len(m["images"])} if m.get("images") else {}),
            }
            for m in messages
        ]
        with self.client.start_as_current_observation(
            name=name,
            as_type="generation",
            model=model,
            input=safe,
            version=prompt,
            metadata={"prompt": prompt},
        ) as gen:
            yield gen

    def flush(self) -> None:
        if self.client is not None:
            self.client.flush()


class _NoGeneration:
    def update(self, **_: Any) -> None:
        pass


@lru_cache(maxsize=1)
def get_tracer() -> Tracer:
    return Tracer()
