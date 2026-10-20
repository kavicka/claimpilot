# ADR-015: Approved invoices leave as Peppol BIS Billing 3.0 UBL

Status: accepted, 2026-10-16

## Decision
- An approved invoice or credit note is sent to the mock ERP as a UBL 2.1 `Invoice` or
  `CreditNote` that follows Peppol BIS Billing 3.0 (EN 16931).
- The document is built in code from normalized, handler-approved values, never from model output.
- The mock ERP applies a subset of the EN 16931 and Peppol business rules (the ones an invoice
  from this pipeline can break: parties, dates, totals, VAT breakdown, line amounts, payment
  account) and names the rule and the field when it refuses. It does not run the full UBL schema
  or the Schematron sets; a real ERP would. A refused invoice goes back to review
  with that reason.
- Nothing is exported without a handler's approval, fast track included.

## Why
- EN 16931 is the European standard for electronic invoices, and Slovakia plans mandatory
  structured B2B invoices on that basis from 2027, so this is the format an ERP will expect.
- Building from normalized values keeps the "LLM extracts, code decides" rule (ADR-002) up to the
  last step.

## Consequences
- The mock ERP holds the master data (suppliers, orders, goods receipts, catalogue) and the UBL
  intake; it runs as its own service next to `core_mock`, locally and in AWS (`erp-mock`).
- The export is safe to repeat. The worker sends the invoice id as `Idempotency-Key`; the ERP
  answers a repeat with the first `erp_id` (200), refuses another document with the same supplier
  and number (409, naming the id it holds) and the same key with other content (422). A refusal
  is never a success: the invoice goes back to review with the reason in `Invoice.export`, and
  `erp_id` stays empty unless the ERP accepted this invoice's document.
- Every call to the ERP carries a bearer token when one is configured (`CLAIMPILOT_ERP_TOKEN`,
  `ERP_MOCK_TOKEN`); `/health` stays open.
- `exported` and `export_refused` rows go to the audit log (actor `system`).
- A crash between the ERP's answer and the database commit leaves the invoice APPROVED; the sweep
  re-drives it and the key makes the second POST harmless.
