FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependency layer first: only lockfile and project manifests.
COPY pyproject.toml uv.lock ./
COPY packages/claimpilot_core/pyproject.toml packages/claimpilot_core/
COPY services/api/pyproject.toml services/api/
COPY services/worker/pyproject.toml services/worker/
COPY services/core_mock/pyproject.toml services/core_mock/
COPY services/mcp_server/pyproject.toml services/mcp_server/
COPY data/generator/pyproject.toml data/generator/
COPY evals/pyproject.toml evals/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package claimpilot-worker

COPY packages packages
COPY services/worker services/worker
COPY config config
COPY prompts prompts
# Policy terms: the worker builds the coverage index from them on first start (ADR-008)
COPY data/policies data/policies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package claimpilot-worker

ENV PATH="/app/.venv/bin:$PATH" HF_HOME=/app/.cache/huggingface

# Every model goes into the image: the ECS task has no internet route and runs with
# HF_HUB_OFFLINE=1. The second run proves the loads work offline. CI's image test skips it
# (PREFETCH=0); the deploy builds with it.
ARG PREFETCH=1
RUN if [ "$PREFETCH" = "1" ]; then claimpilot-prefetch && claimpilot-prefetch --check; fi

CMD ["claimpilot-worker"]

# In Phase 1 this image only runs in CI (unit tests inside the image) so the native worker cannot
# drift from it. In Phase 2 it becomes the ECS task, where Docling and the reranker run on CPU.
