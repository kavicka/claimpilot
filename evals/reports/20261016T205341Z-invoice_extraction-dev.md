# Eval `invoice_extraction` on `dev`

Run 20261016T205341Z · git a115981 (dirty) · dataset 6bd4025701dc · cassettes auto

| Metric | Value |
| --- | ---: |
| kind_accuracy | 100.0% (60/60) |
| header_field_accuracy | 99.1% (1585/1600) |
| line_recall | 100.0% (777/777) |
| line_cell_accuracy | 95.4% (6747/7071) |
| false_values | 8 |
| grounded_share | 96.9% (8137/8395) |
| leaked_values_in_payloads | 0 |

| Ops | Value |
| --- | ---: |
| llm_calls | 176 |
| cached_calls | 6 |
| tokens_in | 451259 |
| tokens_out | 195776 |
| tokens_per_item | 74.0 |
| latency_p50_ms | 35370 |
| latency_p95_ms | 71516 |
| worker_peak_rss_mb | 632 |
| models | ['mlx:mlx-community/Qwen3-8B-4bit+invoice-20261016'] |

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
- column batch: 183/202
- column customs_code: 19/24
- column discount_pct: 232/232
- column ean: 414/640
- column expiry: 202/202
- column gross_unit_price: 137/137
- column line_gross: 232/232
- column line_net: 774/777
- column name: 755/777
- column net_unit_price: 22/22
- column origin: 19/24
- column promo_discount_pct: 7/7
- column quantity: 801/803
- column struct_discount_pct: 14/14
- column sukl_code: 61/94
- column supplier_code: 388/391
- column unit: 731/731
- column unit_price: 771/777
- column vat_amount: 232/232
- column vat_rate: 753/753

## Top failures

| Item | Expected | Got | Detail |
| --- | --- | --- | --- |
| DE-0003/line1.ean | 4003641939483 | None | {} |
| DE-0003/line2.ean | 4009694254405 | None | {} |
| DE-0003/line3.ean | 4002716169336 | None | {} |
| DE-0003/line4.ean | 8581346945115 | None | {} |
| DE-0003/line5.ean | 8584495993358 | None | {} |
| DE-0003/line6.ean | 3803511258574 | None | {} |
| DE-0003/line6.supplier_code | 0023 | 0017 | {} |
| DE-0003/line7.ean | 4006254921913 | None | {} |
| DE-0003/line8.ean | 4004594623696 | None | {} |
| DE-0003/line9.ean | 8585433898896 | None | {} |
