# ADR-005: Rules before LLM in routing

Status: accepted, 2026-10-09

## Decision
Deterministic rules in `config/routing.yaml` decide the queue first (amount thresholds, missing
documents, duplicates, date inconsistencies, events soon after policy start). The LLM sees only claims no
rule decides, gets redacted facts plus the rule hits, and returns one queue value with a rationale.

## Why
Rules are cheaper, auditable and testable; a claims manager can read them. The LLM handles real ambiguity,
not threshold checks.

## Consequences
- Every routing decision stores its rule hits and whether the LLM was used.
- The routing eval weights errors by cost: a missed fraud case costs most.
