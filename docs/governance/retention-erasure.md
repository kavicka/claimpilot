# Retention and erasure

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
