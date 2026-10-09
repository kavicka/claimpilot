# ADR-003: PII never reaches an external model

Status: accepted, 2026-10-09

## Decision
Document text is redacted and tokenized before any model call. Tokens are typed and consistent within a
claim (`<PERSON_1>`, `<RC_1>`, `<IBAN_1>`). Encrypted originals live in `pii.vault`. Re-hydration happens
only in the api (for the handler) and in the submission step. Raw images go to local models only.

## Why
Medical reports are health data, a special category under GDPR Article 9. In Phase 1 every model is
local, but the guard still runs so switching to Bedrock in Phase 2 changes no data flow. Consistent tokens
keep cross-document checks working (same patient on the invoice and the report).

## Consequences
- The leakage test records every outgoing model payload in tests and fails on any ground-truth PII string.
- Logs pass through a filter that replaces vault values.
- Recognizer recall is measured and reported honestly, names included.
