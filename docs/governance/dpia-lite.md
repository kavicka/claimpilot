# DPIA-lite

A short data protection impact assessment for a pilot. A real DPIA would add the controller's legal
basis analysis and the DPO's sign-off.

## Purpose
Prepare travel-insurance claims for a human decision: read documents, check them against the policy
terms, calculate the payout, draft letters. The decision stays with a claims handler.

## Data categories
| Category | Examples | Notes |
| --- | --- | --- |
| Identification | Name, birth number (rodné číslo), date of birth, ID card number, address, phone, e-mail | Redacted before model calls |
| Financial | IBAN, amounts, invoices | IBAN redacted; amounts are needed for the decision |
| Health (GDPR Art. 9) | Diagnoses, medical reports, treatment, alcohol findings | Special category. Needed to assess medical cover; diagnosis text is not redacted because coverage depends on it. Processed only by local models in Phase 1; in Phase 2 it reaches Claude on Bedrock, pseudonymized (no names or identifiers) |
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
| Prompt injection through documents | Hidden text (white, tiny, off-page, invisible, covered) never reaches a model; a detector sends any document that talks to the AI to a senior handler (R10); document text is delimited and its markup made inert; code guards can only make a queue or a verdict stricter; reading calls have no tools (ADR-012) | `injection` suite: decisions changed = 0, detector false positives = 0; `adversarial` suite: 34 attacks, 0 succeeded |
| Data kept too long | Retention job erases finished claims after the retention period; erasure on request. Invoices are covered separately (Phase 3 table below) | retention-erasure.md |
| Logs or traces holding PII | Vault values scrubbed from logs (the most recent 5 000 are kept, the oldest are dropped; the claim being processed is always among the youngest); database errors cut to their first line; traces hold tokens | Unit tests for both; `tests/core/test_logging_secrets.py` (a flood of 100 000 values stays bounded, a recent one is still redacted) |
| Access by unauthorised staff | Login with roles; every action in the audit log | api tests |

## Phase 2 additions (AWS)

| Risk | Mitigation | Evidence |
| --- | --- | --- |
| Health data processed outside the insurer's systems | Text keeps diagnoses but no names or identifiers (pseudonymized); Bedrock with the `eu.` profiles keeps processing in EU Regions; AWS as processor under the AWS DPA; Bedrock does not train on it | provider-terms.md; ADR-010 |
| A name left readable on a page image | Masking from the parser's blocks and an independent text detector; pages OCR could not read are not sent | `masking` eval: 0 personal values readable on 39 dev scans; gate at 0 |
| Handwriting the detector misses | Known gap: no handwritten samples in the synthetic set | ADR-010; needs real samples before production |
| Data reaching the internet from the tasks | No route out of the private subnets; only VPC endpoints | `terraform test`: nothing private has a way out |
| Vault key exposure | Generated outside Terraform, held in Secrets Manager with a customer-managed KMS key, given only to the api and the worker | secrets.tf; `terraform test`: least secrets per task |
| Provider keeps prompts | Bedrock data retention mode set to `none` before go-live; invocation logging stays off; Textract only with the AI opt-out policy | provider-terms.md, deploy.md |

## Phase 3 additions (supplier invoices)

Invoices are company documents. The personal data on them is the supplier's contact person, a
phone number and sometimes a personal e-mail; a sole trader's company name is a person's name.

| Risk | Mitigation | Evidence |
| --- | --- | --- |
| A contact person's name or phone reaching a model | The PII guard runs on invoices as on claims, with IBANs and addresses kept readable (company data the checks need); a name the NER model reads is a company when the document also prints it with a legal form; product names in the item table are never searched for names | `invoice_extraction` suite: leaked values in payloads = 0 (gate); `tests/worker/test_invoice_steps_db.py` |
| Personal data in training data | Training examples are built from prompts as served, so names are tokens; real invoices are never trained on | `tests/evals/test_finetune_data.py`; ADR-014 |
| Real supplier invoices in the repository | Private samples sit in `docs/private-samples/`, gitignored, used only for local reports | `.gitignore`; ADR-013 |
| A sole trader's name kept readable as a company name | Known gap: a name with no legal form next to it is redacted, one with a legal form is not; a sole trader printed as "Ján Novák" is redacted, "Ján Novák - PHARMA" is not | needs real samples before production |
| Invoices kept after the people on them need to be | Two steps (ADR-016): after `personal_data_days` (365) or on request, the vault entries, page text, uploaded file, renders, stored file name and handlers' notes are erased and the accounting record (values, audit trail, `export.xml`) stays; after `invoice_years` (10) full calendar years the case and every file are deleted. The conflict with the accounting duty is resolved by keeping the record, not the people | `tests/core/test_erasure_invoices_db.py`, `tests/worker/test_purge_db.py`; periods in `config/invoices.yaml` |
| Erasure missing a copy of an invoice | `invoices/<id>/` (upload and `export.xml`) is removed with the case; renders and vault go in both steps. The ERP holds the booked invoice and is the company's accounting record; database snapshots hold rows until they expire | ADR-016; `deploy.md` |
| Hostile or oversized uploads exhausting the worker | Upload size and rate limits at intake (25 MB, 60 per minute per token); a page limit, a pixel cap per rendered page and an item limit (400) send an unreadable or oversized document back as NEEDS_INFO; every step has a time budget and a case whose step fails three times is FAILED, not retried again; `/ready` and an ECS health check expose a dead worker. Known gap: the worker still parses untrusted PDFs in its own process; a sandboxed subprocess would be the next step | `tests/api/test_intake_limits_db.py`, `tests/worker/test_renders.py`, `tests/worker/test_pipeline_limits_db.py` |
