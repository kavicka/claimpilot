# ADR-006: Synthetic data only

Status: accepted, 2026-10-09

## Decision
All claims, people and documents are generated. Ground truth comes from the generator, not from manual
labelling.

## Why
Real claims contain health data and cannot be used for a portfolio project. A generator gives exact
ground truth for every field, PII entity and expected decision, at any volume, with controlled edge cases.

## Consequences
- The generator is code with invariant tests (checksums, sums, date order, quotas).
- Generated PDFs are gitignored; the manifest and seed are committed, so `make data SEED=42` reproduces them.
- The expected payout comes from a separate reference calculation in the generator, so one bug cannot
  hide in both the generator and the payout engine.
