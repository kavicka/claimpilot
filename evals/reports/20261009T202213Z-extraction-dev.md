# Eval `extraction` on `dev`

Run 20261009T202213Z · git 6e3c07a (dirty) · dataset 4aee4de982d2 · cassettes replay

| Metric | Value |
| --- | ---: |
| critical_field_accuracy | 97.6% (160/164) |
| all_field_f1 | 92.1% (720/843) |
| all_field_precision | 92.8% (720/776) |
| all_field_recall | 91.5% (720/787) |
| grounded_share | 82.4% (640/777) |
| leaked_values_in_payloads | 0 |
| calibration_error | 0.113 (n=776) |
| straight_through_rate | 55.6% (15/27) |
| straight_through_correct | 100.0% (15/15) |

| Ops | Value |
| --- | ---: |
| llm_calls | 39 |
| cached_calls | 39 |
| tokens_in | 81426 |
| tokens_out | 32847 |
| tokens_per_item | 144.1 |
| latency_p50_ms | 0 |
| latency_p95_ms | 0 |
| worker_peak_rss_mb | 886 |
| models | ['ollama:qwen3-vl:8b'] |

- 109 few-shot source documents left out of the metrics
- critical claim_form: 95/95
- critical medical_invoice: 33/36
- critical medical_report: 23/24
- critical pharmacy_receipt: 6/6
- critical property_irregularity_report: 3/3
- critical on scans 160/164, on digital PDFs 0/0

## Top failures

| Item | Expected | Got | Detail |
| --- | --- | --- | --- |
| S42-002/D1/claimed_items[1].amount | None | — | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "Jednorazové plnenie za zlomeninu — —", "kind": "fp"} |
| S42-002/D1/claimed_items[1].currency | None | — | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "Jednorazové plnenie za zlomeninu — —", "kind": "fp"} |
| S42-002/D3/patient_name | Gabriela Salajová | Gabriela Salajová, geb. 17.08.1965 | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": true, "confidence": 0.9, "quote": "<PERSON_1>, geb. 17.08.1965", "kind": "pair"} |
| S42-002/D3/total | 560.19 | 560.19 Fr. | {"doc_type": "medical_invoice", "scan": true, "language": "de", "grounded": true, "confidence": 0.55, "quote": "Gesamtbetrag 560.19 Fr.", "kind": "pair"} |
| S42-006/D3/icd10_code | M51.2 | MKCH-10 M51.2 | {"doc_type": "medical_report", "scan": true, "language": "sk", "grounded": true, "confidence": 0.9, "quote": "MKCH-10 M51.2", "kind": "pair"} |
| S42-006/D3/patient_birth_date | 23. 2. 1969 | 29. 2. 1969 | {"doc_type": "medical_report", "scan": true, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "29. 2. 1969", "kind": "pair"} |
| S42-010/D1/claimed_items[4].description | Kniha a čítačka | Kniha a čítanka | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": false, "confidence": 0.45, "quote": "Kniha a čítanka 170,07 EUR", "kind": "pair"} |
| S42-015/D4/invoice_number | R-2026-11155 | R-2020-1155 | {"doc_type": "medical_invoice", "scan": true, "language": "hr", "grounded": true, "confidence": 0.9, "quote": "Račun br. R-2020-1155", "kind": "pair"} |
| S42-015/D4/line_items[0].amount | 969,33 | 48.50 | {"doc_type": "medical_invoice", "scan": true, "language": "hr", "grounded": true, "confidence": 0.55, "quote": "34 Bolnički dan 1", "kind": "pair"} |
| S42-015/D4/line_items[1].amount | 969,33 | 28.27 | {"doc_type": "medical_invoice", "scan": true, "language": "hr", "grounded": true, "confidence": 0.55, "quote": "35 Bolnički dan 2", "kind": "pair"} |
