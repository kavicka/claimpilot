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
    uv sync --frozen --no-dev --no-install-workspace --package claimpilot-mcp

COPY packages packages
COPY services/mcp_server services/mcp_server
COPY config config
COPY prompts prompts
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package claimpilot-mcp

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["claimpilot-mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
