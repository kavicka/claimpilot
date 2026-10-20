# Production readiness: supplier invoices

State after the hardening round of 2026-10-20 (branch `phase-3/hardening`). Short version: the
pipeline is sound and its failure modes are named, but it has not met a real ERP, a real identity
provider or enough real invoices. Read "Open" before calling it ready.

## Closed in this round

| Finding of the audit | Fix |
| --- | --- |
| A handler could clear the fraud signal (correct the IBAN, reassess) and approve | Corrections, reassess, retry, escalate and decisions in `fraud_review` and `senior` need a senior; claims too |
| Unknown or unreadable VAT rate exported as 0 %; missing currency exported as EUR | The export stops with the field's name; allowed rates and currencies live in `config/invoices.yaml` |
| Senior limit ignored the currency and a missing amount | Limit per currency; an amount that was not read, or a currency without a limit, goes to a senior (I6) |
| Total tolerance grew with the number of lines | VAT per line or per rate, each exact within one cent |
| Model copied the total into net, VAT and second-currency total, or added up the recap itself and invented a net | Dropped in code unless the number is printed on the page; total and amount due are held against the recap's own sums, so one wrong net is one finding, not three |
| Quantity digits lost on a real layout (pale grey zero decimals marked as hidden text) | Words are hidden only when a span covers 90 % of them; such a tail is no injection signal |
| Export not idempotent, 409 treated as success, no ERP credentials, no audit | `Idempotency-Key`, 409 is a refusal, bearer token, `exported` / `export_refused` audit rows |
| No ERP in the AWS stack | `infra/terraform/erp.tf`; `make infra-check` 0 failed |
| Demo-password identity, role in the cookie, no user admin | `users.active`, role read from the database on every request, `claimpilot-admin`, production mode refuses to start with demo or empty secrets |
| Login throttle per username and per task | Per (username, IP), counters in Redis with a bounded in-process fallback |
| Blind approval (no version), same person corrects and approves | Decisions and corrections need `version`; four eyes above `approval.four_eyes_amount` |
| Duplicates compared raw and racy | Normalized number and an advisory lock per (supplier, number) |
| Invoices never retained or erased | ADR-016: personal data erased after 365 days, record and `export.xml` kept 10 years |
| Step timeouts never reached FAILED; poison invoice blocked the queue | Step budgets, FAILED after 3 error runs, item limit (400) to NEEDS_INFO |
| `/health` checked Postgres only; no intake limits; unbounded log scrubber | `/ready` (db, Redis, worker heartbeat), upload size and rate limits, bounded scrubber |

## Open

Blockers for a real deployment:

- **A real ERP.** The mock is in memory and applies a subset of EN 16931 and Peppol. Nothing has
  been posted to a real system. Needs an adapter, a Schematron run in CI, and a real key policy.
- **A real identity provider.** Local users with scrypt passwords and an admin CLI exist; SSO,
  MFA and self-service password change do not.
- **Real invoices.** A handful of private samples ran through the pipeline locally on a live
  model; they are not part of the repository and not an accuracy figure. Remaining failures there
  were single lines (a VAT amount taken from the rate) and an invoice that prints no VAT rate (a
  handler decides). A pilot with a real supplier mix and handlers correcting is the measure.
- **Receipts invoiced twice and credit notes with an original that exists only in the ERP**
  (two separate tasks, not merged here).

Should fix:

- The worker parses untrusted PDFs in-process; a worker killed by OOM leaves no error row.
- Behind the load balancer the login throttle is per username until
  `CLAIMPILOT_TRUST_FORWARDED_FOR` is set (Terraform does not set it).
- After a crash that follows a successful ERP post, a corrected invoice is sent with the same
  idempotency key and a different document and gets 422.
- The LoRA adapter was refused by the eval gate; extraction still runs on `qwen3:30b` through
  Ollama. A cloud or fine-tuned path is a cost and accuracy decision, not a code gap.
- Portal clients share one rate-limit bucket.
