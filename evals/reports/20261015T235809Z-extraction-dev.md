# Eval `extraction` on `dev`

Run 20261015T235809Z · git 4f6ae4b (dirty) · dataset 6bd4025701dc · cassettes auto

| Metric | Value |
| --- | ---: |
| critical_field_accuracy | 99.1% (450/454) |
| all_field_f1 | 96.4% (1762/1894) |
| all_field_precision | 96.6% (1762/1824) |
| all_field_recall | 96.2% (1762/1832) |
| grounded_share | 94.8% (1731/1825) |
| leaked_values_in_payloads | 0 |
| calibration_error | 0.070 (n=1824) |
| straight_through_rate | 85.0% (34/40) |
| straight_through_correct | 100.0% (34/34) |

| Ops | Value |
| --- | ---: |
| llm_calls | 112 |
| cached_calls | 112 |
| tokens_in | 273687 |
| tokens_out | 84209 |
| tokens_per_item | 194.4 |
| latency_p50_ms | 0 |
| latency_p95_ms | 0 |
| worker_peak_rss_mb | 1072 |
| models | ['ollama:qwen3-vl:8b', 'ollama:qwen3:30b-a3b-instruct-2507-q4_K_M'] |

- 36 few-shot source documents left out of the metrics
- critical claim_form: 190/190
- critical medical_invoice: 73/76
- critical medical_report: 62/63
- critical pharmacy_receipt: 24/24
- critical policy_certificate: 92/92
- critical property_irregularity_report: 9/9
- critical on scans 160/164, on digital PDFs 290/290

## Top failures

| Item | Expected | Got | Detail |
| --- | --- | --- | --- |
| S42-002/D1/claimed_items[1].amount | None | — | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "Jednorazové plnenie za zlomeninu — —", "kind": "fp"} |
| S42-002/D1/claimed_items[1].currency | None | — | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "Jednorazové plnenie za zlomeninu — —", "kind": "fp"} |
| S42-002/D3/patient_name | Gabriela Salajová | Gabriela Salajová, geb. 17. 8. 1965 | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": true, "confidence": 0.95, "quote": "<PERSON_1>, geb. <DOB_1>", "kind": "pair"} |
| S42-002/D3/total | 560.19 | 560.19 Fr. | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": true, "confidence": 0.55, "quote": "Gesamtbetrag 560.19 Fr.", "kind": "pair"} |
| S42-006/D3/icd10_code | M51.2 | MKCH-10 M51.2 | {"doc_type": "medical_report", "scan": true, "language": "sk", "grounded": true, "confidence": 0.95, "quote": "MKCH-10 M51.2", "kind": "pair"} |
| S42-006/D3/patient_birth_date | 23. 2. 1969 | 29. 2. 1969 | {"doc_type": "medical_report", "scan": true, "language": "sk", "grounded": false, "confidence": 0.3, "quote": "29. 2. 1969", "kind": "pair"} |
| S42-009/D1/claimed_items[1].amount | None | - | {"doc_type": "claim_form", "scan": false, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "Jednorazové plnenie za zlomeninu \| -", "kind": "fp"} |
| S42-009/D1/claimed_items[1].currency | None | None | {"doc_type": "claim_form", "scan": false, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "Jednorazové plnenie za zlomeninu \| -", "kind": "fp"} |
| S42-010/D1/claimed_items[4].description | Kniha a čítačka | Kniha a čítanka | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": false, "confidence": 0.45, "quote": "Kniha a čítanka 170,07 EUR", "kind": "pair"} |
| S42-010/D3/delivery_time | None | NOT DELIVERED | {"doc_type": "property_irregularity_report", "scan": false, "language": "en", "grounded": true, "confidence": 0.55, "quote": "DELIVERED TO PASSENGER NOT DELIVER |
