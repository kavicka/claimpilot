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
    uv sync --frozen --no-dev --no-install-workspace --package claimpilot-core-mock

COPY packages packages
COPY services/core_mock services/core_mock
COPY config config
COPY prompts prompts
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package claimpilot-core-mock

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "claimpilot_core_mock.main:app", "--host", "0.0.0.0", "--port", "8000"]
