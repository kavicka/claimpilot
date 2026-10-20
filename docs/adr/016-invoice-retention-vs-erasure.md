# ADR-016: Invoices are kept as accounting records and erased in two steps

Status: accepted, 2026-10-20

## Context
A claim is personal data from the first page; erasing it whole is the right answer to an
erasure request (Art. 17) and to the end of the retention period. A supplier invoice is also an
accounting document. Slovak accounting law (zákon č. 431/2002 Z. z., § 35) makes the company
keep accounting documents for ten years, counted from the end of the accounting period they belong
to. That conflicts with a request to erase the people named on it (a contact person, a phone, a
sole trader's name): Art. 17(3)(b) lets the controller keep what a legal duty requires, and no
more. Before this change the pipeline did neither: `erase_claim` found only claims, its
`rmtree` covered `claims/` but not `invoices/<id>/`, and the purge job selected claims only.

## Decision
- Two steps, with the periods in the `retention:` block of `config/invoices.yaml` (not in code):
  1. **Personal data** (`erase_invoice_personal_data`), `personal_data_days: 365` after the
     invoice reached a final state (EXPORTED or REJECTED), or on request:
     - the invoice's vault entries are deleted, so its tokens resolve to nobody;
     - `doc_blocks.text` and `doc_cells.text` are replaced by their redacted text (text that never
       got a redacted form becomes empty: it cannot be told from a name);
     - the uploaded file and the page renders are deleted; the document row's file name, which
       often holds a supplier's or person's name, becomes `erased.<ext>`;
     - handlers' free-text notes in the audit log are removed (the action stays);
     - one audit line `personal_data_erased` records the date and the reason.
     Kept: the header and line values, validation and matching results, the audit trail and
     `invoices/<id>/export.xml` (the UBL document sent to the ERP).
  2. **Full deletion** (`erase_case`), when `invoice_years: 10` full calendar years have passed
     after the year the invoice closed in: rows, the whole `invoices/<id>/` folder (so
     `export.xml` too) and renders. One audit line with the reference stays.
- The clock is `cases.updated_at`, the last change of the case. Erasing personal data does not
  touch the case row, so it does not restart the clock.
- Closed means EXPORTED, REJECTED, and also NEEDS_INFO or FAILED that nobody has touched for
  `personal_data_days`: an abandoned invoice would otherwise keep a supplier's contact person
  forever. The same periods apply to them.
- Erasure on request: `DELETE /api/review/invoices/{id}/personal-data` with a reason, senior
  handlers only, refused (409) while the invoice is still in the pipeline or in review. It runs
  step 1 only. A request for full deletion of an invoice inside its accounting period is refused by
  design: the record is the legal duty. Claims keep `DELETE /api/review/claims/{id}` (whole case).
- The daily purge (03:15) runs claims, step 1 and step 2 in that order, one case per transaction,
  so a case that cannot be erased (a read-only disk) is logged and does not hold back the others.

## Why
- Keeping the whole case for ten years keeps people's names, phones and page text for no reason
  the accounting duty requires; the duty covers the amounts, parties, dates and the document
  that was booked. Redacted text and the UBL document are that record.
- Deleting the vault entries rather than the extracted fields keeps the record auditable (a field
  still says what was read) while the token no longer leads to a person.
- A calendar-year rule is conservative where the law counts from the period end; a fixed
  `years * 365 days` rule would delete a December invoice up to a year early.

## Consequences
- Placeholder periods: ten years is the statutory minimum for accounting documents; the personal
  data period (one year) is a pilot default. The controller and its accountant set the real
  values; both are one-line config changes.
- The accounting record still holds company data kept readable on purpose (addresses, IBANs of
  companies) and, for a sole trader printed with a legal form, a name that was not tokenized
  (known gap in dpia-lite.md). A sole trader's request for erasure of that name is not served by
  step 1; it needs a manual correction of the extracted field.
- Langfuse traces hold tokenized text only; after step 1 the tokens resolve to nothing.
- Backups and the ERP copy are outside this system's reach: the ERP holds the booked invoice and is
  the accounting record of the company; an RDS snapshot keeps rows for the snapshot period.
- Tests: `tests/core/test_erasure_invoices_db.py`, `tests/worker/test_purge_db.py`,
  `tests/api/test_retention_api_db.py`, `tests/core/test_retention.py`.
