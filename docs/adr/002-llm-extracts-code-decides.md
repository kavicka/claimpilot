# ADR-002: LLM extracts, code decides

Status: accepted, 2026-10-09

## Decision
Models read documents and map text to closed sets (document type, coverage category, queue when rules
cannot decide). Money, limits, deductibles, FX conversion, date arithmetic and the payout never run
inside a model.

## Why
A wrong payout is the most expensive error in claims handling, and it must be reproducible and
explainable. Python with tests gives the same answer every time; a model does not. The Day 1 smoke test
also showed local models return amounts as printed ("279,50"), so normalization belongs in code anyway.

## Consequences
- Extraction schemas return values as printed strings; validators and normalizers turn them into
  Decimal amounts, ISO dates and ISO 4217 currencies.
- The payout engine is plain Python, written test-first with property tests.
- Prompts never contain arithmetic instructions.
