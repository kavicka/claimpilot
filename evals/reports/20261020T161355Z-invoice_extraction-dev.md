# Eval `invoice_extraction` on `dev`

Run 20261020T161355Z · git 25e335a (dirty) · dataset 6bd4025701dc · cassettes auto

| Metric | Value |
| --- | ---: |
| kind_accuracy | 100.0% (60/60) |
| header_field_accuracy | 98.8% (1580/1600) |
| line_recall | 100.0% (777/777) |
| line_cell_accuracy | 99.7% (7050/7071) |
| false_values | 105 |
| grounded_share | 96.4% (8447/8762) |
| leaked_values_in_payloads | 0 |

| Ops | Value |
| --- | ---: |
| llm_calls | 176 |
| cached_calls | 176 |
| tokens_in | 450555 |
| tokens_out | 276242 |
| tokens_per_item | 82.3 |
| latency_p50_ms | 0 |
| latency_p95_ms | 0 |
| worker_peak_rss_mb | 670 |
| models | ['ollama:qwen3:30b-a3b-instruct-2507-q4_K_M'] |

- DE-0001 sap: lines 3/3
- DE-0002 sap: lines 2/2
- DE-0003 pohoda: lines 18/18
- DE-0004 wholesale: lines 27/27
- DE-0005 tangram: lines 10/10
- DE-0006 scan_en: lines 3/3
- DE-0007 scan_en: lines 3/3
- DE-0008 tangram: lines 15/15
- DE-0009 sap: lines 3/3
- DE-0010 wholesale: lines 24/24
- DE-0011 tangram: lines 12/12
- DE-0012 tangram: lines 18/18
- DE-0013 sap: lines 4/4
- DE-0014 pohoda: lines 10/9
- DE-0015 scan_en: lines 1/1
- DE-0016 pohoda: lines 1/1
- DE-0017 pohoda: lines 25/25
- DE-0018 sap: lines 2/2
- DE-0019 wholesale: lines 15/15
- DE-0020 scan_en: lines 1/1
- DE-0021 scan_en: lines 2/2
- DE-0022 tangram: lines 17/17
- DE-0023 pohoda: lines 2/2
- DE-0024 sap: lines 1/1
- DE-0025 tangram: lines 13/13
- DE-0026 wholesale: lines 16/16
- DE-0027 pohoda: lines 25/24
- DE-0028 pohoda: lines 19/19
- DE-0029 pohoda: lines 20/20
- DE-0030 wholesale: lines 24/24
- DE-0031 pohoda: lines 2/2
- DE-0032 pohoda: lines 20/19
- DE-0033 pohoda: lines 25/25
- DE-0034 scan_en: lines 3/3
- DE-0035 wholesale: lines 42/42
- DE-0036 wholesale: lines 30/30
- DE-0038 scan_en: lines 2/2
- DE-0039 wholesale: lines 17/17
- DE-0040 wholesale: lines 41/41
- DE-0042 scan_en: lines 3/3
- DE-0043 wholesale: lines 18/18
- DE-0044 wholesale: lines 9/9
- DE-0045 scan_en: lines 3/3
- DE-0046 tangram: lines 7/7
- DE-0047 pohoda: lines 20/20
- DE-0048 pohoda: lines 21/21
- DE-0049 wholesale: lines 17/17
- DE-0050 sap: lines 1/1
- DE-0051 tangram: lines 10/10
- DE-0052 tangram: lines 17/17
- DE-0053 pohoda: lines 2/2
- DE-0054 sap: lines 2/2
- DE-0055 wholesale: lines 25/25
- DE-0056 wholesale: lines 13/13
- DE-0057 wholesale: lines 44/44
- DE-0058 tangram: lines 18/18
- DE-0059 sap: lines 2/2
- DE-0060 scan_en: lines 3/3
- DE-D001 sap: lines 2/2
- DE-D002 pohoda: lines 25/25
- column batch: 202/202
- column customs_code: 24/24
- column discount_pct: 232/232
- column ean: 640/640
- column expiry: 202/202
- column gross_unit_price: 137/137
- column line_gross: 232/232
- column line_net: 777/777
- column name: 761/777
- column net_unit_price: 19/22
- column origin: 24/24
- column promo_discount_pct: 7/7
- column quantity: 801/803
- column struct_discount_pct: 14/14
- column sukl_code: 94/94
- column supplier_code: 391/391
- column unit: 731/731
- column unit_price: 777/777
- column vat_amount: 232/232
- column vat_rate: 753/753

## Top failures

| Item | Expected | Got | Detail |
| --- | --- | --- | --- |
| DE-0001/header.supplier_vat_id | CZ95474463 | SK2997673481 | {} |
| DE-0001/line1.unit | None | Kusy | {} |
| DE-0001/line2.unit | None | Kusy | {} |
| DE-0001/line3.unit | None | Kusy | {} |
| DE-0002/line1.unit | None | Kusy | {} |
| DE-0002/line2.unit | None | Kusy | {} |
| DE-0004/header.constant_symbol | None | 252971779 | {} |
| DE-0004/header.total_net | None | 14.357,3100 | {} |
| DE-0006/header.buyer_name | Lekárne Sever Retail s.r.o. | karne Seyer Retail s.r.c | {} |
| DE-0006/header.supplier_dic | None | CZ94545154 | {} |
