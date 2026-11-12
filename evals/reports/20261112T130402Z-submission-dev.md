# Eval `submission` on `dev`

Run 20261112T130402Z · git 0482a78 (dirty) · dataset 6bd4025701dc · cassettes auto

| Metric | Value |
| --- | ---: |
| first_try_success | 97.3% (36/37) |
| after_retry_success | 97.3% (36/37) |
| invented_values | 0 |
| agent_used_on_perturbed | 97.3% (36/37) |

| Ops | Value |
| --- | ---: |
| llm_calls | 208 |
| cached_calls | 208 |
| tokens_in | 360998 |
| tokens_out | 111908 |
| tokens_per_item | 6390.6 |
| latency_p50_ms | 0 |
| latency_p95_ms | 0 |
| worker_peak_rss_mb | 1648 |
| models | ['ollama:qwen3-vl:8b', 'ollama:qwen3:14b', 'ollama:qwen3:30b-a3b-instruct-2507-q4_K_M', 'ollama:qwen3:4b-instruct'] |

## Top failures

| Item | Expected | Got | Detail |
| --- | --- | --- | --- |
| S42-030/clean | registered | needs_handler | {"submissions": 0, "first_try": false, "agent": false, "invented": [], "fields": ["event_country"], "errors": []} |
| S42-030/perturbed | registered | needs_handler | {"submissions": 0, "first_try": false, "agent": false, "invented": [], "fields": ["event_country"], "errors": []} |
