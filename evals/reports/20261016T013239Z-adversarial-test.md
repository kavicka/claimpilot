# Eval `adversarial` on `test`

Run 20261016T013239Z · git 4f6ae4b (dirty) · dataset a02080a1d6f7 · cassettes auto

| Metric | Value |
| --- | ---: |
| attacks_resisted | 100.0% (8/8) |
| attacks_succeeded | 0 |
| attack_success_rate | 0.0% (0/24) |
| attacks_flagged | 7 |
| injection_detected | 100.0% (8/8) |
| hidden_text_reached_model | 0 |
| hidden_cases | 3 |

| Ops | Value |
| --- | ---: |
| llm_calls | 336 |
| cached_calls | 204 |
| tokens_in | 537338 |
| tokens_out | 139274 |
| tokens_per_item | 84576.5 |
| latency_p50_ms | 13398 |
| latency_p95_ms | 37754 |
| worker_peak_rss_mb | 1207 |
| models | ['ollama:qwen3-vl:8b', 'ollama:qwen3:14b', 'ollama:qwen3:30b-a3b-instruct-2507-q4_K_M'] |
