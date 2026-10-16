# ADR-014: Invoice extraction learns through a local LoRA adapter behind an eval gate

Status: accepted, 2026-10-16

## Decision
- Handler corrections on invoices, together with a synthetic train split, train a LoRA adapter on
  Qwen3-8B (4-bit MLX weights, `mlx-lm` on Apple silicon). `mlx_lm.server` serves the base model
  and picks the adapter per request; `LLMGateway` reaches it as provider `mlx`
  (`mlx:<base>+<adapter>`). No conversion to GGUF: the adapter is used as trained.
- The server has no schema-constrained decoding. The adapter learns the JSON shape from its
  training answers; the gateway's retry with the validation error stays the safety net.
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
- The base model is Qwen3-8B (owner's choice, 2026-10-16): it trains in the 48 GB next to a
  stopped compose stack. 14B stays an option if the first gate run shows 8B cannot reach the
  current model.
- Adapter weights stay local (gitignored); the commit carries their training config and the
  reports. Running the promoted config needs `make mlx-serve` next to the worker.

## First run, 2026-10-16 (`invoice-20261016`, 300 iterations ≈ 1 epoch): not promoted
- The gate refused it: line-cell accuracy fell from 99.7 % to 95.4 % on dev. Header accuracy rose
  (98.8 % → 99.1 %) and false values fell (122 → 8), so the format was learned; what it lost are
  the fields printed on an item's continuation lines — EAN (-226), ŠUKL code (-33), batch (-19),
  origin and customs code (-5 each).
- It drops EAN on the pohoda layout (225 of 232) and keeps it everywhere else, and it does so on
  a training prompt too, answering it field for field except that one pair. So the field was not
  learned, not forgotten at inference.
- Training loss 0.003 and validation loss 0.004 did not show this: one missing field is a handful
  of tokens in a long answer, so token loss cannot see it. The eval gate is what caught it, and
  a gate failure now prints the per-column deltas that name the field.
- Next attempt: more epochs before anything else (300 iterations with batch 1 and 4 accumulation
  steps is about one pass over 1183 examples).
