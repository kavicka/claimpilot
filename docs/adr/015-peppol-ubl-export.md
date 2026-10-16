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
  intake; it runs as its own service next to `core_mock`.
