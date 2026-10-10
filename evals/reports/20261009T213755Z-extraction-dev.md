# Eval `extraction` on `dev`

Run 20261009T213755Z · git 6e3c07a (dirty) · dataset 4aee4de982d2 · cassettes auto

| Metric | Value |
| --- | ---: |
| critical_field_accuracy | 98.6% (204/207) |
| all_field_f1 | 97.1% (879/932) |
| all_field_precision | 96.7% (879/909) |
| all_field_recall | 97.5% (879/902) |
| grounded_share | 94.1% (855/909) |
| leaked_values_in_payloads | 0 |
| calibration_error | 0.093 (n=909) |
| straight_through_rate | 65.0% (13/20) |
| straight_through_correct | 100.0% (13/13) |

| Ops | Value |
| --- | ---: |
| llm_calls | 50 |
| cached_calls | 50 |
| tokens_in | 132333 |
| tokens_out | 41032 |
| tokens_per_item | 190.7 |
| latency_p50_ms | 0 |
| latency_p95_ms | 0 |
| worker_peak_rss_mb | 1009 |
| models | ['ollama:qwen3-vl:8b', 'ollama:qwen3:30b-a3b-instruct-2507-q4_K_M'] |

- 23 few-shot source documents left out of the metrics
- critical claim_form: 95/95
- critical medical_invoice: 30/32
- critical medical_report: 26/27
- critical pharmacy_receipt: 3/3
- critical policy_certificate: 44/44
- critical property_irregularity_report: 6/6
- critical on scans 55/58, on digital PDFs 149/149

## Top failures

| Item | Expected | Got | Detail |
| --- | --- | --- | --- |
| S42-002/D1/claimed_items[1].amount | None | — | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "Jednorazové plnenie za zlomeninu — —", "kind": "fp"} |
| S42-002/D1/claimed_items[1].currency | None | — | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "Jednorazové plnenie za zlomeninu — —", "kind": "fp"} |
| S42-002/D3/patient_name | Gabriela Salajová | Gabriela Salajová, geb. 17.08.1965 | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": true, "confidence": 0.9, "quote": "<PERSON_1>, geb. 17.08.1965", "kind": "pair"} |
| S42-002/D3/total | 560.19 | 560.19 Fr. | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": true, "confidence": 0.55, "quote": "Gesamtbetrag 560.19 Fr.", "kind": "pair"} |
| S42-006/D3/icd10_code | M51.2 | MKCH-10 M51.2 | {"doc_type": "medical_report", "scan": true, "language": "sk", "grounded": true, "confidence": 0.9, "quote": "MKCH-10 M51.2", "kind": "pair"} |
| S42-006/D3/patient_birth_date | 23. 2. 1969 | 29. 2. 1969 | {"doc_type": "medical_report", "scan": true, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "29. 2. 1969", "kind": "pair"} |
| S42-009/D1/claimed_items[1].amount | None | - | {"doc_type": "claim_form", "scan": false, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "Jednorazové plnenie za zlomeninu \| -", "kind": "fp"} |
| S42-009/D1/claimed_items[1].currency | None | None | {"doc_type": "claim_form", "scan": false, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "Jednorazové plnenie za zlomeninu \| -", "kind": "fp"} |
| S42-010/D1/claimed_items[4].description | Kniha a čítačka | Kniha a čítanka | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": false, "confidence": 0.45, "quote": "Kniha a čítanka 170,07 EUR", "kind": "pair"} |
| S42-010/D3/delivery_time | None | NOT DELIVERED | {"doc_type": "property_irregularity_report", "scan": false, "language": "en", "grounded": true, "confidence": 0.55, "quote": "DELIVERED TO PASSENGER NOT DELIVER |
