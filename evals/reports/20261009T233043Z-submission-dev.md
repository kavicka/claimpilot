# Eval `submission` on `dev`

Run 20261009T233043Z · git bab3d7e (dirty) · dataset 4aee4de982d2 · cassettes auto

| Metric | Value |
| --- | ---: |
| first_try_success | 97.3% (36/37) |
| after_retry_success | 97.3% (36/37) |
| invented_values | 0 |
| agent_used_on_perturbed | 97.3% (36/37) |

| Ops | Value |
| --- | ---: |
| llm_calls | 218 |
| cached_calls | 158 |
| tokens_in | 363399 |
| tokens_out | 113831 |
| tokens_per_item | 6449.1 |
| latency_p50_ms | 7967 |
| latency_p95_ms | 18572 |
| worker_peak_rss_mb | 1240 |
| models | ['ollama:qwen3-vl:8b', 'ollama:qwen3:14b', 'ollama:qwen3:30b-a3b-instruct-2507-q4_K_M', 'ollama:qwen3:4b-instruct'] |

## Top failures

| Item | Expected | Got | Detail |
| --- | --- | --- | --- |
| S42-030/clean | registered | needs_handler | {"submissions": 0, "first_try": false, "agent": false, "invented": [], "fields": ["event_country"], "errors": []} |
| S42-030/perturbed | registered | needs_handler | {"submissions": 0, "first_try": false, "agent": false, "invented": [], "fields": ["event_country"], "errors": []} |
