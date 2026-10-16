# ADR-013: Supplier invoices as a second domain on a shared core

Status: accepted, 2026-10-16

## Decision
- ClaimPilot also processes purchase invoices that wholesalers send to a pharmacy chain: invoices,
  credit notes and proformas. Same pipeline idea: parse, redact, extract with sources, decide in
  code, a handler approves.
- A case is the unit the pipeline moves. `cases` holds what every kind needs (kind, reference,
  status, queue, error, lock version); `claims` and `invoices` hold what only their domain has and
  share the case's primary key (joined-table inheritance on `kind`).
- Documents, extracted fields, step runs, the audit log and the vault hang off `case_id`. Routing,
  coverage and summary tables stay claim-only until invoices need their own.
- One state machine per kind (`state_machine.claims`, `state_machine.invoices`), and pipeline
  steps registered per (kind, status). Extraction checks are registered per document type.
- Real sample invoices stay outside git (`docs/private-samples/`, `data/real/`); they are a
  local eval set only. Everything committed or trained on is synthetic (ADR-006).

## Why
- Most of the work for an invoice is the work for a claim: Docling, the PII guard, the LLM
  gateway, grounding, rule-first decisions, the review UI, evals with cassettes. A second repo
  would copy all of it.
- Keeping a claim's case id equal to its old claim id made the migration a rename: no row changes
  its key, and a fingerprint of a copy of the dev database is the same before the upgrade, after it
  and after the downgrade.
- A shared table for the status and the lock version lets the worker, the sweep and the review API
  handle any kind with the same code, and keeps the optimistic lock on one row.

## Consequences
- An ORM `UPDATE` must name the table that holds the column: `update(Case)` for status or
  `updated_at`, `update(Claim)` for claim columns. `select(Claim)` returns claims only.
- Queries that compare a claim with other claims (duplicate files, reused receipt numbers,
  operations metrics) join `claims`, so invoices do not leak into claim checks.
- Invoice statuses: RECEIVED, PARSED, REDACTED, EXTRACTED, VALIDATED, MATCHED, ROUTED, IN_REVIEW,
  then a handler's APPROVED, REJECTED or NEEDS_INFO; APPROVED leads to EXPORTED, or back to review
  when the ERP refuses the document.
