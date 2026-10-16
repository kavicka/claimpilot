# ADR-014: Invoice extraction learns through a local LoRA adapter behind an eval gate

Status: accepted, 2026-10-16

## Decision
- Handler corrections on invoices, together with a synthetic train split, train a LoRA adapter for
  the local extraction model (`mlx-lm` on Apple silicon). The adapter is served by Ollama as its
  own model name.
- Training starts by hand (`make finetune`). The adapter replaces the current model in
  `config/providers.yaml` only when it beats it on the dev split: line-cell accuracy rises and no
  other gated metric drops beyond its tolerance. The test split runs once per promoted adapter.
- Training records hold the redacted prompt as served and the corrected output: tokens stay
  tokens, so no personal value enters training.
- Real invoices are never trained on. They are scored locally on demand (`invoices_real`), like
  the `masking` suite.
- The cloud path (Claude on Bedrock) is not fine-tuned; it is compared against the local base and
  the local adapter in the eval report.

## Why
- The owner wants the system to learn from corrections. Fine-tuning is the form of learning that
  changes the model itself; the eval gate keeps it from silently getting worse.
- Synthetic invoices give exact ground truth at any volume, so the adapter can be trained before
  any handler has corrected anything.
- A manual start keeps memory under control: training and the compose stack do not run together
  on a 48 GB machine.

## Consequences
- Every promotion is a commit with its eval report.
- The base model size (8B or 14B) is chosen by the first eval, not up front.
