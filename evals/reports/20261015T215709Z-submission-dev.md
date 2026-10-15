# Eval `submission` on `dev`

Run 20261015T215709Z · git bd6a8ac (dirty) · dataset 4aee4de982d2 · cassettes auto

| Metric | Value |
| --- | ---: |
| first_try_success | 97.3% (36/37) |
| after_retry_success | 97.3% (36/37) |
| invented_values | 0 |
| agent_used_on_perturbed | 97.3% (36/37) |

| Ops | Value |
| --- | ---: |
| llm_calls | 211 |
| cached_calls | 211 |
| tokens_in | 361570 |
| tokens_out | 112653 |
| tokens_per_item | 6408.4 |
| latency_p50_ms | 0 |
| latency_p95_ms | 0 |
| worker_peak_rss_mb | 1600 |
| models | ['ollama:qwen3-vl:8b', 'ollama:qwen3:14b', 'ollama:qwen3:30b-a3b-instruct-2507-q4_K_M', 'ollama:qwen3:4b-instruct'] |

## Top failures

| Item | Expected | Got | Detail |
| --- | --- | --- | --- |
| S42-030/clean | registered | needs_handler | {"submissions": 0, "first_try": false, "agent": false, "invented": [], "fields": ["event_country"], "errors": []} |
| S42-030/perturbed | registered | needs_handler | {"submissions": 0, "first_try": false, "agent": false, "invented": [], "fields": ["event_country"], "errors": []} |
