# Eval `invoice_extraction` on `dev`

Run 20261112T130723Z · git 0482a78 (dirty) · dataset 6bd4025701dc · cassettes auto

| Metric | Value |
| --- | ---: |
| kind_accuracy | 100.0% (60/60) |
| header_field_accuracy | 97.5% (1544/1584) |
| line_recall | 99.4% (713/717) |
| line_cell_accuracy | 98.6% (6353/6440) |
| false_values | 115 |
| grounded_share | 96.6% (7776/8053) |
| leaked_values_in_payloads | 0 |

| Ops | Value |
| --- | ---: |
| llm_calls | 167 |
| cached_calls | 167 |
| tokens_in | 423434 |
| tokens_out | 256006 |
| tokens_per_item | 82.9 |
| latency_p50_ms | 0 |
| latency_p95_ms | 0 |
| worker_peak_rss_mb | 1677 |
| models | ['ollama:qwen3:30b-a3b-instruct-2507-q4_K_M'] |

- DE-0001 sap: lines 3/3
- DE-0002 sap: lines 3/3
- DE-0003 pohoda: lines 17/17
- DE-0004 wholesale: lines 25/25
- DE-0005 tangram: lines 10/10
- DE-0006 scan_en: lines 3/3
- DE-0007 scan_en: lines 4/4
- DE-0008 tangram: lines 17/17
- DE-0009 sap: lines 1/1
- DE-0010 wholesale: lines 31/31
- DE-0011 tangram: lines 16/16
- DE-0012 tangram: lines 15/15
- DE-0013 sap: lines 6/6
- DE-0014 pohoda: lines 27/26
- DE-0015 scan_en: lines 3/3
- DE-0016 pohoda: lines 2/2
- DE-0017 pohoda: lines 8/8
- DE-0018 sap: lines 6/6
- DE-0019 wholesale: lines 25/25
- DE-0020 scan_en: lines 1/1
- DE-0021 scan_en: lines 2/2
- DE-0022 tangram: lines 7/7
- DE-0023 pohoda: lines 1/1
- DE-0024 sap: lines 6/6
- DE-0025 tangram: lines 11/11
- DE-0026 wholesale: lines 23/23
- DE-0027 pohoda: lines 19/18
- DE-0028 pohoda: lines 8/8
- DE-0029 pohoda: lines 20/20
- DE-0030 wholesale: lines 26/26
- DE-0031 pohoda: lines 2/2
- DE-0032 pohoda: lines 12/11
- DE-0033 pohoda: lines 14/14
- DE-0034 scan_en: lines 3/3
- DE-0035 wholesale: lines 44/44
- DE-0036 wholesale: lines 28/28
- DE-0038 scan_en: lines 1/1
- DE-0039 wholesale: lines 16/16
- DE-0040 wholesale: lines 27/27
- DE-0042 scan_en: lines 3/3
- DE-0043 wholesale: lines 32/32
- DE-0044 wholesale: lines 17/17
- DE-0045 scan_en: lines 0/4
- DE-0046 tangram: lines 6/6
- DE-0047 pohoda: lines 17/17
- DE-0048 pohoda: lines 21/21
- DE-0049 wholesale: lines 15/15
- DE-0050 sap: lines 2/2
- DE-0051 tangram: lines 10/10
- DE-0052 tangram: lines 9/9
- DE-0053 pohoda: lines 1/1
- DE-0054 sap: lines 3/3
- DE-0055 wholesale: lines 14/14
- DE-0056 wholesale: lines 32/32
- DE-0057 wholesale: lines 8/8
- DE-0058 tangram: lines 11/11
- DE-0059 sap: lines 1/1
- DE-0060 scan_en: lines 3/3
- DE-D001 pohoda: lines 17/17
- DE-D002 scan_en: lines 1/1
- column batch: 195/202
- column customs_code: 21/28
- column discount_pct: 183/183
- column ean: 601/605
- column expiry: 195/202
- column gross_unit_price: 112/112
- column line_gross: 183/183
- column line_net: 711/717
- column name: 694/717
- column net_unit_price: 22/31
- column origin: 24/28
- column promo_discount_pct: 8/8
- column quantity: 731/743
- column struct_discount_pct: 17/17
- column sukl_code: 91/91
- column supplier_code: 322/326
- column unit: 658/658
- column unit_price: 713/717
- column vat_amount: 183/183
- column vat_rate: 689/689

## Top failures

| Item | Expected | Got | Detail |
| --- | --- | --- | --- |
| DE-0001/header.supplier_vat_id | CZ92793100 | SK2997673481 | {} |
| DE-0001/line1.net_unit_price | 8,90 | None | {} |
| DE-0001/line1.unit | None | Kusy | {} |
| DE-0001/line2.net_unit_price | 2,67 | None | {} |
| DE-0001/line2.unit | None | Kusy | {} |
| DE-0001/line3.net_unit_price | 13,81 | None | {} |
| DE-0001/line3.unit | None | Kusy | {} |
| DE-0002/header.supplier_vat_id | CZ92793100 | SK2992944152 | {} |
| DE-0002/line1.unit | None | Kusy | {} |
| DE-0002/line2.unit | None | Kusy | {} |
