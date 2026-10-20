# Retention and erasure

Claims and invoices differ: a claim is erased whole, an invoice is an accounting record and is
erased in two steps (ADR-016).

## Claims
- **Retention:** finished claims (SUBMITTED or REJECTED) older than `CLAIMPILOT_RETENTION_DAYS`
  (default 3650 days, a placeholder for the insurer's retention schedule) are erased by the worker's
  daily purge job at 03:15.
- **Erasure on request:** a senior handler calls `DELETE /api/review/claims/{id}` with a reason.
- **What erasure removes:** the claim and every row under it (documents, text blocks, extracted
  fields, corrections, routing and coverage decisions, letters, step runs) through the database's
  cascades; the vault entries behind its tokens; uploaded files and page renders.
- **What stays:** one audit line with the claim reference and the reason. Langfuse traces keep
  tokenized text only; with the vault entries gone, the tokens no longer resolve to anyone.
- **Tests:** `tests/core/test_erasure_db.py`.

## Invoices
Periods are in the `retention:` block at the end of `config/invoices.yaml`.

| Step | When | Removes | Keeps |
| --- | --- | --- | --- |
| 1. Personal data | `personal_data_days` (365) after EXPORTED or REJECTED, or after NEEDS_INFO or FAILED has sat untouched that long; or on request: `DELETE /api/review/invoices/{id}/personal-data`, senior handler, invoice not in the pipeline | vault entries; page text (replaced by its redacted form); the uploaded file and page renders; the stored file name; handlers' free-text notes | header, lines, validation and matching results, audit trail (with one `personal_data_erased` line), `export.xml` |
| 2. Full deletion | `invoice_years` (10) full calendar years after the year the invoice closed in | the case, all rows under it, the whole `invoices/<id>/` folder including `export.xml`, renders, vault | one audit line with the reference and the reason |

- The retention clock is the case's last change (`cases.updated_at`); step 1 does not touch it.
- A request to erase an invoice inside its accounting period removes the people, not the record:
  the accounting duty (Art. 17(3)(b)) covers the booked document.
- The daily purge handles each case in its own transaction; a failure is logged (`purge.failed`)
  and the next night tries again.
- **Tests:** `tests/core/test_erasure_invoices_db.py`, `tests/worker/test_purge_db.py`,
  `tests/api/test_retention_api_db.py`, `tests/core/test_retention.py`.
