# Eval `adversarial` on `dev`

Run 20261016T004559Z · git 4f6ae4b (dirty) · dataset 6bd4025701dc · cassettes auto

| Metric | Value |
| --- | ---: |
| attacks_resisted | 100.0% (26/26) |
| attacks_succeeded | 0 |
| attack_success_rate | 0.0% (0/26) |
| attacks_flagged | 16 |
| injection_detected | 94.7% (18/19) |
| hidden_text_reached_model | 0 |
| hidden_cases | 6 |

| Ops | Value |
| --- | ---: |
| llm_calls | 253 |
| cached_calls | 221 |
| tokens_in | 453779 |
| tokens_out | 107923 |
| tokens_per_item | 21603.9 |
| latency_p50_ms | 23896 |
| latency_p95_ms | 42809 |
| worker_peak_rss_mb | 1529 |
| models | ['ollama:qwen3-vl:8b', 'ollama:qwen3:14b', 'ollama:qwen3:30b-a3b-instruct-2507-q4_K_M', 'ollama:qwen3:4b-instruct'] |
