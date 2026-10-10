# Eval `retrieval` on `test`

Run 20261009T223412Z · git bab3d7e (dirty) · dataset d59d01befdf0 · cassettes auto

| Metric | Value |
| --- | ---: |
| recall_at_5 | 83.3% (20/24) |
| mrr | 0.712 (n=24) |
| recall_at_5_exclusions | 0.0% (0/1) |

| Ops | Value |
| --- | ---: |
| llm_calls | 72 |
| cached_calls | 71 |
| tokens_in | 176434 |
| tokens_out | 51127 |
| tokens_per_item | 9481.7 |
| latency_p50_ms | 16373 |
| latency_p95_ms | 16373 |
| worker_peak_rss_mb | 1159 |
| models | ['ollama:qwen3-vl:8b', 'ollama:qwen3:30b-a3b-instruct-2507-q4_K_M', 'ollama:qwen3:4b-instruct'] |

- index: 46 clauses

## Top failures

| Item | Expected | Got | Detail |
| --- | --- | --- | --- |
| S42-049/I1 | ['A11.2'] | ['A4.1', 'A4.2', 'A5.2', 'A5.1', 'A4.3'] | {"coverage": "medical", "verdict": "not_covered", "exclusion": "alcohol_or_drugs"} |
| S42-055/I1 | ['A7.1', 'A7.2'] | ['A7.5', 'A7.4', 'A7.1', 'A7.6', 'A7.3'] | {"coverage": "luggage", "verdict": "covered", "exclusion": null} |
| S42-055/I2 | ['A7.1', 'A7.2'] | ['A7.5', 'A7.4', 'A7.6', 'A7.1', 'A7.3'] | {"coverage": "luggage", "verdict": "covered", "exclusion": null} |
| S42-055/I3 | ['A7.1', 'A7.2'] | ['A7.5', 'A7.4', 'A7.1', 'A7.6', 'A7.3'] | {"coverage": "luggage", "verdict": "covered", "exclusion": null} |
