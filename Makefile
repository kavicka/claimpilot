SHELL := /bin/bash
SEED ?= 42
SUITE ?= all
SPLIT ?= dev
MODELS := qwen3:14b qwen3-vl:8b bge-m3 qwen3:4b-instruct qwen3:30b-a3b-instruct-2507-q4_K_M gemma3:12b

.PHONY: help up up-obs down logs ps migrate worker api test test-db lint fmt typecheck check \
        smoke data eval-fast eval compare vault-key models ui seed mcp fewshot corrections e2e \
        infra-check deploy destroy finetune mlx-serve

help:  ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

up:  ## Start Postgres, Redis, api, core_mock, mcp_server; apply migrations
	docker compose up -d --build --wait postgres redis api core_mock erp_mock mcp_server
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

worker:  ## Run the arq worker natively (MPS), restarted when Redis goes away
	uv run claimpilot-worker

api:  ## Run the api natively with reload (instead of the container)
	uv run uvicorn claimpilot_api.main:app --port 4400 --reload

test:  ## Unit tests (no live models, no database)
	uv run pytest

e2e:  ## Playwright tests of the review UI against the api and a seeded database (no models)
	cd ui && pnpm e2e

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

finetune:  ## Train an invoice LoRA adapter (MLX), promote it only if the eval gate passes (ADR-014)
	uv run claimpilot-eval finetune --name $(or $(NAME),invoice-$(shell date +%Y%m%d)) --iters $(or $(ITERS),300)

mlx-serve:  ## Serve the adapter base model for the promoted invoice steps (port 4430)
	uv run python -m mlx_lm server --model mlx-community/Qwen3-8B-4bit --port 4430

data-invoices:  ## Generate the synthetic supplier invoices and their ERP records
	uv run claimpilot-datagen invoices --seed $(or $(SEED),42)

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
	pnpm --dir ui install --prefer-offline --silent # refreshes the copy of packages/claimpilot-ui
	pnpm --dir ui dev

seed:  ## Upload N synthetic dev claims through the api (N=5)
	uv run claimpilot-eval seed --split dev --n $(or $(N),5)

mcp:  ## Read-only MCP server on stdio (for Claude Code / Claude Desktop)
	uv run claimpilot-mcp

fewshot:  ## Rebuild extraction few-shot examples from dev
	uv run claimpilot-eval fewshot

corrections:  ## Export handler corrections as a dataset
	uv run claimpilot-eval export-corrections

TFLINT := docker run --rm -e TFLINT_PLUGIN_DIR=/data/.tflint.d -v $(CURDIR)/infra/terraform:/data -w /data \
	--entrypoint sh ghcr.io/terraform-linters/tflint:v0.59.1 -c

infra-check:  ## Terraform fmt, validate, mocked tests, tflint, checkov (no AWS account needed)
	terraform -chdir=infra/terraform fmt -check -recursive
	terraform -chdir=infra/terraform init -backend=false -input=false >/dev/null
	terraform -chdir=infra/terraform validate
	terraform -chdir=infra/terraform test
	terraform -chdir=infra/terraform/bootstrap init -backend=false -input=false >/dev/null
	terraform -chdir=infra/terraform/bootstrap validate
	$(TFLINT) "tflint --init >/dev/null && tflint --recursive"
	checkov -d infra/terraform --framework terraform --quiet --compact

deploy:  ## Deploy to AWS (docs/deploy.md); needs AWS credentials and terraform.tfvars
	scripts/deploy/deploy.sh

destroy:  ## Remove the AWS stack; keeps the state bucket and a final DB snapshot
	scripts/deploy/destroy.sh
