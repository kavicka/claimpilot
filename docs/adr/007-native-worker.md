# ADR-007: Native worker in Phase 1

Status: accepted, 2026-10-09

## Decision
The worker runs natively on macOS (`make worker`), next to Ollama. Postgres, Redis, Langfuse, api,
core_mock and mcp_server run in Docker Compose.

## Why
Containers on a Mac get no Metal GPU access. Docling's layout and OCR models, the reranker and the NER
model run on MPS in the native worker and on CPU inside Docker.

## Consequences
- The worker reads Postgres and Redis on their published localhost ports and uploads from `data/storage`,
  which the api container mounts.
- CI builds the worker image (CPU torch on Linux) and runs the unit tests inside it on every push, so the
  native setup cannot drift from the image that becomes the ECS task in Phase 2.
