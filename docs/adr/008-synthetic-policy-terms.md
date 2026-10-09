# ADR-008: Synthetic policy terms (VPP) as the coverage corpus

Status: accepted, 2026-10-09

## Decision
The coverage RAG corpus is a synthetic set of travel-insurance policy terms (VPP) written in Slovak for
the fictional insurer used across the project. It follows the structure of public Slovak travel VPP
documents (články, odseky, výluky, limity) but copies no text from them.

## Why
- Ground truth needs exact clause IDs for every covered and excluded item. With our own terms the
  generator knows which clause decides each item.
- Public VPP documents carry insurer branding and reuse terms; the plan already ruled out committing them.
- Limits and deductibles in `data/policies/products.yaml` and the clause text stay consistent by
  construction.

## Consequences
- The plan's "download 1-2 public VPP documents" step becomes "write the synthetic VPP". A real public VPP
  can still be added later as a robustness check for retrieval, kept out of the repo.
- Retrieval evals measure recall on our clause IDs; numbers on real VPP text would need hand labelling.
