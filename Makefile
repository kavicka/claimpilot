SHELL := /bin/bash
SEED ?= 42
SUITE ?= all
SPLIT ?= dev
MODELS := qwen3:14b qwen3-vl:8b bge-m3 qwen3:4b-instruct qwen3:30b-a3b-instruct-2507-q4_K_M

.PHONY: help up up-obs down logs ps migrate worker api test test-db lint fmt typecheck check \
        smoke data eval-fast eval compare vault-key models ui

help:  ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

up:  ## Start Postgres, Redis, api, core_mock, mcp_server; apply migrations
	docker compose up -d --build --wait postgres redis api core_mock mcp_server
	uv run alembic upgrade head

up-obs:  ## Also start self-hosted Langfuse on :4420
	docker compose --profile observability up -d --wait

down:  ## Stop everything
	docker compose --profile observability down

logs:  ## Follow container logs
	docker compose logs -f --tail=100

ps:  ## Container status
	docker compose ps

migrate:  ## Apply migrations to the dev and test databases
	uv run alembic upgrade head
	ALEMBIC_DATABASE_URL=postgresql+psycopg://claimpilot:claimpilot@127.0.0.1:5438/claimpilot_test uv run alembic upgrade head

worker:  ## Run the arq worker natively (MPS)
	uv run arq claimpilot_worker.main.WorkerSettings

api:  ## Run the api natively with reload (instead of the container)
	uv run uvicorn claimpilot_api.main:app --port 4400 --reload

test:  ## Unit tests (no live models, no database)
	uv run pytest

test-db:  ## Tests that need the compose Postgres
	uv run pytest -m db

lint:  ## Ruff lint and format check
	uv run ruff check .
	uv run ruff format --check .

fmt:  ## Format and autofix
	uv run ruff format .
	uv run ruff check --fix .

typecheck:  ## Pyright
	uv run pyright

check: lint typecheck test  ## Everything CI runs

smoke:  ## Day 1 smoke tests against local Ollama
	uv run claimpilot-smoke

data:  ## Generate the synthetic claims dataset
	uv run claimpilot-datagen generate --seed $(SEED)

eval-fast:  ## Gated suites on the dev split, then compare against baselines
	uv run claimpilot-eval run --suite $(SUITE) --split dev --fast
	uv run claimpilot-eval-compare --latest

eval:  ## Full live eval run (records cassettes)
	uv run claimpilot-eval run --suite $(SUITE) --split $(SPLIT) --record
	uv run claimpilot-eval-compare --latest

vault-key:  ## Print a new Fernet key for CLAIMPILOT_PII_VAULT_KEY
	@uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

models:  ## Pull the local models
	for m in $(MODELS); do ollama pull $$m; done

ui:  ## Review UI dev server on :4410
	pnpm --dir ui dev
