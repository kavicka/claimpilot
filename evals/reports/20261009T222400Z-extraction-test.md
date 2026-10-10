# Eval `extraction` on `test`

Run 20261009T222400Z · git bab3d7e (dirty) · dataset d59d01befdf0 · cassettes auto

| Metric | Value |
| --- | ---: |
| critical_field_accuracy | 99.3% (295/297) |
| all_field_f1 | 94.9% (1107/1225) |
| all_field_precision | 95.9% (1107/1154) |
| all_field_recall | 94.0% (1107/1178) |
| grounded_share | 93.8% (1083/1155) |
| leaked_values_in_payloads | 1 |
| calibration_error | 0.093 (n=1154) |
| straight_through_rate | 70.0% (14/20) |
| straight_through_correct | 100.0% (14/14) |

| Ops | Value |
| --- | ---: |
| llm_calls | 76 |
| cached_calls | 3 |
| tokens_in | 191258 |
| tokens_out | 54928 |
| tokens_per_item | 207.8 |
| latency_p50_ms | 19104 |
| latency_p95_ms | 37512 |
| worker_peak_rss_mb | 1432 |
| models | ['ollama:qwen3-vl:8b', 'ollama:qwen3:30b-a3b-instruct-2507-q4_K_M'] |

- 0 few-shot source documents left out of the metrics
- critical booking_confirmation: 3/3
- critical claim_form: 100/100
- critical medical_invoice: 55/56
- critical medical_report: 50/51
- critical pharmacy_receipt: 15/15
- critical police_report: 2/2
- critical policy_certificate: 64/64
- critical property_irregularity_report: 6/6
- critical on scans 78/80, on digital PDFs 217/217

## Top failures

| Item | Expected | Got | Detail |
| --- | --- | --- | --- |
| S42-042/D2/passenger_name | STRYCEKOVA/ZUZANA MS | Zuzana Strýčeková MS | {"doc_type": "property_irregularity_report", "scan": false, "language": "en", "grounded": true, "confidence": 0.9, "quote": "PASSENGER NAME <PERSON_1> MS \| BAG  |
| S42-043/D1/claimed_items[1].amount | None | – | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "Jednorazové plnenie za zlomeninu –", "kind": "fp"} |
| S42-043/D1/claimed_items[1].currency | None | None | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": true, "confidence": 0.55, "quote": "Jednorazové plnenie za zlomeninu –", "kind": "fp"} |
| S42-044/D5/pharmacy_name | Ljekarna Hrženjak | Ljekarna Hrženjak Dubrovnik | {"doc_type": "pharmacy_receipt", "scan": false, "language": "hr", "grounded": true, "confidence": 0.9, "quote": "Ljekarna Hrženjak Dubrovnik", "kind": "pair"} |
| S42-045/D3/diagnosis | Uganuće gležnja | Uganuće glezňa | {"doc_type": "medical_report", "scan": true, "language": "hr", "grounded": true, "confidence": 0.9, "quote": "DIJAGNOZA Uganiuće glezňa", "kind": "pair"} |
| S42-045/D4/patient_name | Silvia Jedľovská | <PERSON_3> | {"doc_type": "medical_invoice", "scan": true, "language": "hr", "grounded": true, "confidence": 0.9, "quote": "<PERSON_3>, rođen/a 16.02.1989.", "kind": "pair"} |
| S42-045/D5/line_items[0].description | Elastični zavoj | Elastični zavoј | {"doc_type": "pharmacy_receipt", "scan": true, "language": "hr", "grounded": false, "confidence": 0.45, "quote": "Elastični zavoј 8,61", "kind": "pair"} |
| S42-045/D5/receipt_number | 1857/92691 | 57/9291 | {"doc_type": "pharmacy_receipt", "scan": true, "language": "hr", "grounded": false, "confidence": 0.45, "quote": "Broj računa 57/9291", "kind": "pair"} |
| S42-046/D1/claimed_items[3].description | Oblečenie (nohavice, tričká) | Oblečenie (nohavice, trčká) | {"doc_type": "claim_form", "scan": true, "language": "sk", "grounded": false, "confidence": 0.45, "quote": "Oblečenie (nohavice, trčká) 161,57 EUR", "kind": "pa |
| S42-046/D2/delivery_time | None | NOT DELIVERED | {"doc_type": "property_irregularity_report", "scan": false, "language": "en", "grounded": true, "confidence": 0.55, "quote": "DELIVERED TO PASSENGER NOT DELIVER |
