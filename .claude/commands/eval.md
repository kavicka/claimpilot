---
description: Run an eval suite on the dev split and report the delta against its baseline
argument-hint: <suite> [--model step=model]
---
Run `uv run claimpilot-eval run --suite $ARGUMENTS --split dev` and then `uv run claimpilot-eval-compare --latest`.

Report in this order, briefly:
1. Gate result (pass or which rule tripped).
2. Metric deltas against the baseline, with counts next to percentages (9/10, not only 90%).
3. Newly failing items: document, field, expected, got.
4. Tokens, p95 latency and peak memory compared with the baseline.

Never update a baseline unless the user asks.
