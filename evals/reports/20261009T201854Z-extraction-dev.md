# Eval `extraction` on `dev`

Run 20261009T201854Z · git 6e3c07a (dirty) · dataset 4aee4de982d2 · cassettes replay

| Metric | Value |
| --- | ---: |
| critical_field_accuracy | 81.1% (133/164) |
| all_field_f1 | 88.6% (674/847) |
| all_field_precision | 91.8% (674/734) |
| all_field_recall | 85.6% (674/787) |
| grounded_share | 93.6% (733/783) |
| leaked_values_in_payloads | 0 |
| calibration_error | 0.027 (n=734) |
| straight_through_rate | 51.9% (14/27) |
| straight_through_correct | 92.9% (13/14) |

| Ops | Value |
| --- | ---: |
| llm_calls | 39 |
| cached_calls | 39 |
| tokens_in | 112026 |
| tokens_out | 33174 |
| tokens_per_item | 183.6 |
| latency_p50_ms | 0 |
| latency_p95_ms | 0 |
| worker_peak_rss_mb | 830 |
| models | ['ollama:qwen3:30b-a3b-instruct-2507-q4_K_M'] |

- 109 few-shot source documents left out of the metrics
- critical claim_form: 93/95
- critical medical_invoice: 19/36
- critical medical_report: 17/24
- critical pharmacy_receipt: 4/6
- critical property_irregularity_report: 0/3
- critical on scans 133/164, on digital PDFs 0/0

## Top failures

| Item | Expected | Got | Detail |
| --- | --- | --- | --- |
| S42-002/D1/claimed_items[1].amount | None | 560,19 | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": true, "confidence": 0.95, "quote": "Jednorazové plnenie za zlomeninu \| 560,19 \| CHF", "ki |
| S42-002/D1/claimed_items[1].currency | None | CHF | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": true, "confidence": 0.95, "quote": "Jednorazové plnenie za zlomeninu \| 560,19 \| CHF", "ki |
| S42-002/D3/invoice_number | RE-2026-84748 | None | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": false, "confidence": 0.0, "quote": "", "kind": "fn"} |
| S42-002/D3/issue_date | 23.07.2026 | None | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": false, "confidence": 0.0, "quote": "", "kind": "fn"} |
| S42-002/D3/line_items[0].description | Notfallbehandlung | Röntgen | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": true, "confidence": 0.9, "quote": "2 \| Röntgen \| 270.37", "kind": "pair"} |
| S42-002/D3/line_items[1].description | Röntgen | Gipsverband | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": true, "confidence": 0.9, "quote": "3 \| Gipsverband \| 118.29", "kind": "pair"} |
| S42-002/D3/line_items[2].description | Gipsverband | Physiotherapie | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": true, "confidence": 0.9, "quote": "4 \| Physiotherapie \| 101.60", "kind": "pair"} |
| S42-002/D3/line_items[3].amount | 69.93 | None | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": null, "confidence": null, "quote": null, "kind": "fn"} |
| S42-002/D3/line_items[3].description | Physiotherapie | None | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": null, "confidence": null, "quote": null, "kind": "fn"} |
| S42-002/D3/provider_name | Medizinisches Zentrum Frei | Medizinisches Zentrum Frei medizinisches Zentrum Frei | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": true, "confidence": 0.9, "quote": "Medizinisches Zentrum Frei medizinisches Zentrum  |
