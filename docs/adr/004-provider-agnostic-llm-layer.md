# ADR-004: Provider-agnostic LLM layer

Status: accepted, 2026-10-09

## Decision
Every model call goes through `LLMGateway`. The model and provider for each pipeline step come from
`config/providers.yaml`. The eval runner overrides them per run to compare configurations.

## Why
The best model differs per step (a 4B model types documents, a 14B model extracts, a 30B model writes
letters). Model choice is an eval result, not a code change. Bedrock joins in Phase 2 as one more adapter.

## Consequences
- Extraction-type calls use the provider's native JSON-schema output (constrained decoding), which is more
  reliable than tool calling on local models. The submission agent is the one tool-using step.
- Thinking is off by default: on qwen3:14b it tripled latency (8 s to 22 s) with identical values in the
  Day 1 smoke test. A step turns it on only when its eval improves.
- Cassettes record responses per prompt hash and model, so CI replays without a model.
