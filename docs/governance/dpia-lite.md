# DPIA-lite

A short data protection impact assessment for a pilot. A real DPIA would add the controller's legal
basis analysis and the DPO's sign-off.

## Purpose
Prepare travel-insurance claims for a human decision: read documents, check them against the policy
terms, calculate the payout, draft letters. The decision stays with a claims handler.

## Data categories
| Category | Examples | Notes |
| --- | --- | --- |
| Identification | Name, birth number (rodné číslo), ID card number, address, phone, e-mail | Redacted before model calls |
| Financial | IBAN, amounts, invoices | IBAN redacted; amounts are needed for the decision |
| Health (GDPR Art. 9) | Diagnoses, medical reports, treatment, alcohol findings | Special category. Needed to assess medical cover; diagnosis text is not redacted because coverage depends on it. Processed only by local models in Phase 1 |
| Travel | Destinations, dates, flights, bookings | Needed for the policy period and trip checks |
| Third parties | Physicians, police officers | Names redacted like the insured's |

## Legal basis (hypothesis for the pilot)
Performance of the insurance contract (Art. 6(1)(b)); health data under Art. 9(2)(f) (legal claims)
or explicit consent in the claim form, as the insurer's existing claims process already relies on.

## Risks and mitigations
| Risk | Mitigation | Evidence |
| --- | --- | --- |
| Personal data sent to an external model | Redaction at one point (worker), leakage test on every eval run, the vision step refuses non-local providers | `pii` suite: 0 leaked values; `leaked_values_in_payloads` = 0 in every suite |
| Wrong decision against the client | No automated decisions: a handler approves every claim; payouts computed by tested code | Human oversight doc; payout engine property tests |
| Hallucinated values | Every value carries a quote matched to the page; unmatched values are flagged and capped in confidence | Extraction suite: grounded share, calibration |
| Prompt injection through documents | Documents delimited as data, extraction calls have no tools, injected documents in the eval set | `injection` suite: decisions changed = 0 |
| Data kept too long | Retention job erases finished claims after the retention period; erasure on request | retention-erasure.md |
| Logs or traces holding PII | Vault values scrubbed from logs; database errors cut to their first line; traces hold tokens | Unit tests for both |
| Access by unauthorised staff | Login with roles; every action in the audit log | api tests |
