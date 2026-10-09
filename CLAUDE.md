# ClaimPilot

AI pipeline for travel-insurance claims: documents in, a handler-approved decision out. Local-first
portfolio project. The plan and build steps live in the ClaimPilot Implementation Plan doc
(tabs "Implementation Plan" and "Build steps").

## Architecture

- `services/api` (FastAPI, Docker): stores uploads, enqueues jobs, serves the review UI. No model calls.
- `services/worker` (arq, **native macOS**): every pipeline step and every model call. Runs natively so
  Docling, the reranker and NER get MPS. CI builds and tests its Docker image anyway.
- `services/core_mock` (FastAPI, Docker): the target core claims system with strict validation.
- `services/mcp_server` (MCP SDK 2.x `MCPServer`, Docker): read-only tools over the api.
- `packages/claimpilot_core`: domain enums, SQLAlchemy models, LLM gateway, PII vault, state machine.
- `data/generator`: synthetic claims with exact ground truth. `evals/`: runner, suites, baselines, cassettes.
- `ui/`: Next.js review app on :4410.

Pipeline: RECEIVED → PARSED → REDACTED → EXTRACTED → ROUTED → ASSESSED → IN_REVIEW → (handler)
APPROVED → SUBMITTED | REJECTED | NEEDS_INFO. All moves go through `claimpilot_core.state_machine`.

Ports: Postgres 5438 (a native Postgres owns 5432), Redis 6389, api 4400, core_mock 4401,
mcp 4402, ui 4410, Langfuse 4420, Ollama 11434.

## Commands

```
make up          # compose stack + migrations
make worker      # native arq worker
make test        # unit tests, no models, no db
make test-db     # tests marked db, need compose Postgres
make lint typecheck
make smoke       # live Ollama smoke checks
make data SEED=42
make eval-fast   # gated suites on dev, compare with baselines
make eval        # live run that records cassettes
```

## Rules

- **LLM extracts, code decides.** Money, limits, deductibles, FX and date logic never run inside a
  prompt. Schemas return values as printed (strings); code normalizes them.
- **PII never reaches a model unredacted.** Text goes through the PII guard first; tokens like
  `<PERSON_1>` are consistent per claim. Re-hydration happens only in the api and the submission step.
- **Every model call goes through `LLMGateway`.** Model per step in `config/providers.yaml`, thinking
  off unless the step's config turns it on.
- **Prompts are code.** `prompts/<step>/<name>.md` with a `version` in front-matter. After any change in
  `prompts/` or `services/worker/`, run `make eval-fast` and report the metric delta. Commit the new
  report and cassettes with the change; CI fails a suite whose prompt hash has no recording.
- **Tests first for deterministic code**: validators, payout engine, routing rules, state machine,
  fact checker, generator invariants.
- **Rules before LLM** in routing and document typing.
- **Synthetic data only.** No real customer data, no real insurer names or branding.
- Code, docs and README in English. Client-facing outputs in Slovak (formal, vykanie) and German.
- UI copy and docs follow the `no-ai-slop` skill: plain, specific, no filler.

## Layout conventions

- New document type: `/new-doc-type <name>` scaffolds schema, template, generator piece and tests.
- Eval reports land in `evals/reports/`; baselines in `evals/baselines/<suite>.json` keep per-item results.
- ADRs in `docs/adr/`, discovery in `docs/discovery/`, governance in `docs/governance/`.
