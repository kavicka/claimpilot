# Testing

Five layers, from cheapest to most expensive. Everything except the live eval and the local-only
`masking` suite runs in CI on every push, with no model, no generated PDFs and no AWS account.

| Layer | What it checks | Count | Command |
| --- | --- | --- | --- |
| Unit | Deterministic code: state machine, identifiers, PII guard, payout engine, routing rules, prechecks, fact checker, gateway, Bedrock adapter (real SDK, mocked HTTP), masking, parser, Textract adapter, traces, submission agent with a scripted model, document checks, hidden-text and injection detectors, coverage guard | 760 | `make test` |
| Database | The api and the pipeline against Postgres: roles, corrections, erasure, uploads, concurrent writes, Redis outages, step failures, the sweep, hidden text in the review api | 67 | `make test-db` |
| End to end | The review UI in Chromium against the real api and a seeded database: login, queues, field boxes, corrections, senior rules, version conflicts, approve, retry, the prompt-injection warning, manual upload, accessibility (axe) | 12 | `make e2e` |
| Evals | Model behaviour on synthetic claims with ground truth: ten suites, replayed from recorded responses in CI and gated against baselines; an eleventh, `masking`, runs locally only (macOS OCR, generated PDFs) | 10 + 1 suites | `make eval-fast` |
| Infrastructure | The AWS Terraform with mocked providers: no route out of private subnets, encryption, Bedrock only from the worker and only in EU Regions, read-only containers, secrets per task, tracing sidecar, Textract only when chosen; tflint; checkov | 9 test runs | `make infra-check` |

## Edge cases and where they are tested

| Edge case | Expected behaviour | Test |
| --- | --- | --- |
| HEIC, Word, EXE, empty file, PNG renamed to .pdf, HTML renamed to .pdf, file over 20 MB, 21 files | Rejected with a message the client understands (415, 413, 422); nothing stored, not even the good files of the same upload | `tests/api/test_uploads_db.py` |
| File names with `../`, Windows paths, control characters, 300 characters | Shown cleaned and shortened; stored under a generated name | `tests/api/test_uploads_db.py` |
| Password-protected PDF, PDF without pages, PDF over 40 pages, damaged PDF, cut-off image, image claiming 400 megapixels | Claim goes to NEEDS_INFO with a request in Slovak naming each file and its problem, instead of three retries and the dead-letter list | `tests/worker/test_ingest_check.py`, `tests/worker/test_pipeline_db.py`, live run |
| Six uploads at once; an upload after an erasure | Distinct references from a database sequence (they repeated before: `count + 1`) | `tests/api/test_uploads_db.py` |
| Two handlers approve at once; a correction and an approval at once | One wins, the other gets 409; the core system sees one submission | `tests/api/test_concurrency_db.py` |
| A handler approves a claim that changed after their page loaded | 409 "the claim changed since you opened it" (optimistic version on the claim) | `tests/api/test_concurrency_db.py`, `ui/e2e/review.spec.ts` |
| The worker writes a claim a handler changed meanwhile | The worker's write fails and retries with fresh data | `tests/api/test_concurrency_db.py` |
| Worker killed (`kill -9`) in the middle of extraction | Nothing half-written; the job runs again and the claim completes with no duplicate rows | live run (see below) |
| Redis down during an upload | Upload still succeeds; the sweep re-enqueues the claim within 20 minutes | `tests/api/test_resilience_db.py`, `tests/worker/test_pipeline_db.py`, live run |
| Redis down while the worker runs | The supervisor restarts the worker after 2, 5, 10, 30, 60 s | live run |
| Model server down | Retries after 60 and 120 s, then FAILED with the cause; a handler retries it from the UI | `tests/worker/test_pipeline_db.py`, `ui/e2e/review.spec.ts`, live run |
| Tampered, expired or foreign-signed session cookie; garbage cookies | 401 | `tests/api/test_security_db.py` |
| The MCP service account on every write endpoint, on uploads, on page images | 403 or 401 | `tests/api/test_security_db.py`, `tests/api/test_review_db.py` |
| Password guessing | Five failures per account in 15 minutes, then 429; an unknown user and a wrong password look the same, including the time they take | `tests/api/test_security_db.py` |
| A login form submitted before its script loads | POST, so the password never lands in the URL (it did in development before) | `ui/e2e/review.spec.ts` |
| A known name in another form: "Kováčová, Jana", "J. Kováčová", broken across lines, declined ("Jany Kováčovej", "s pánom Petrom Novákom"), surname after "pani" or "Herr" | Replaced by the same token; ordinary words sharing a stem are left alone | `tests/core/test_pii.py` |
| Prompt injection, 34 attacks in six languages: white, 1.5 pt, off-page, invisible, covered text; text burnt into a scan; a fake JSON answer, delimiter break, fake page marker, chat-template role tags; a note to the reviewer; a long page of filler before the instruction; leetspeak, spaced letters, base64; PDF metadata, annotation, form field, file name; a spoofed document type | Compared with the clean claim in the same run: no lower queue, no higher payout, no verdict loosened to covered, no planted amount, no extra NEEDS_INFO, no file name or hidden text in any model request. Text that reaches the parse raises R10 (senior) | `adversarial` suite: dev 26 of 26 resisted, 19/19 detected; held-out test 8 of 8 resisted, 8/8 detected |
| Hidden text in a PDF: contrast under 1.25, font under 4 pt, off the page, render mode 3, transparent, drawn over; white text on a dark banner; a field frame drawn as an even-odd path; a scanner's OCR layer over an image | Hidden text is marked, cut out of its block and never sent to a model; visible text is left alone | `tests/worker/test_hidden_text.py` (0 hits on every generated PDF) |
| A document addresses the AI, overrides its rules, imitates role tags or our JSON, names our labels; ordinary text that looks close ("Bitte ignorieren Sie die erste Rechnung", "al sistema sanitario", "Fast Track lane") | Signal on the first, nothing on the second; 0 false positives on 147 clean dev documents | `tests/worker/test_injection_signals.py`, `injection` suite |
| The coverage model says covered while a report names alcohol, a known condition or an uninsured extreme sport, or while the claim carries R10, or without citing a clause | needs_review, nothing paid automatically; code never loosens a verdict | `tests/worker/test_coverage_guard.py`, `coverage` suite |
| Accessibility on login, queue and claim pages | No serious or critical axe findings | `ui/e2e/review.spec.ts` |
| A date of birth: after its label in any claim language, in its own OCR block after the label block, glued to the block before, or printed in another form elsewhere in the claim | One `<DOB_n>` token per person; visit, invoice and event dates stay | `tests/core/test_pii.py`; `pii` eval: 60/60 on dev |
| A letterhead, form or stamp that Docling files as a picture; running headers and footers | Its text becomes blocks like any other, so the redactor and the text path see it; bare page numbers are dropped | `tests/worker/test_parser.py` |
| A scan sent to a cloud model: a name in a block, an IBAN no document mentioned before, text the parser never read, a page OCR could not read, a personal value without a position, a detector failure | Blacked out, or the images are not sent and the text path reads the document | `tests/worker/test_mask.py`; `masking` eval: 0 values readable on 39 dev scans |
| A model value that lost one character ("R-2026 36818" for "R-2026-36818") on a line grounding found | The value does not match the page as printed, so its confidence stays below straight-through | `tests/worker/test_extraction_logic.py` |
| Claude declines a request (`stop_reason: refusal`) | Retried once on the fallback model; a second refusal sends the claim to a handler | `tests/core/test_bedrock.py` |
| The Bedrock request as the Anthropic SDK sends it | Signed for eu-central-1, `bedrock-runtime` URL with the EU profile, structured output, image blocks first, no temperature or seed | `tests/core/test_bedrock.py` (real SDK, mocked HTTP) |

## Live runs (2026-10-10)

Run against the compose stack and the native worker; not part of CI because they need the models.

| Scenario | What happened |
| --- | --- |
| Mixed upload: a good form, a password-protected PDF, a cut-off JPG | NEEDS_INFO in 4 s with the Slovak request naming both files |
| `kill -9` on the worker during extraction | The open transaction was lost (0 fields written). After the job lock expired the job ran again (attempt 2) and the claim reached review with 50 fields, 1 coverage decision and 3 texts, no duplicates |
| Upload while Redis was stopped | 201, warning in the api log; the worker's sweep picked the claim up on restart and it reached review (fast track, 42.27 EUR as in the ground truth) |
| Redis stopped for 20 s under the supervisor | Worker restarted after 2, 5 and 10 s and processed the next claim |
| Ollama stopped | Extraction failed at 10:19:52, retried at 10:20:52 and 10:22:52, then FAILED with "ConnectError". After Ollama came back, Retry in the api took the claim to review (fast track, 96.08 EUR as in the ground truth) |

## Not covered yet

- Real phone photos (rotation by 90°, perspective, blur, shadows) beyond the generator's light
  scan noise; a robustness curve per degradation.
- Languages outside the six; two claims in one PDF; another patient's invoice inside a claim.
- A larger held-out split with confidence intervals (the test split has 20 claims).
- Load: many claims at once, throughput and memory of the worker.
- Server-side session revocation: a logged-out cookie stays valid until it expires (12 hours).

## Problems found while hardening (stage 1.11)

| Problem | Fix |
| --- | --- |
| Claim references came from `count + 1`: repeated after an erasure, collided under concurrent uploads | Postgres sequence |
| A rejected file in an upload left the earlier files of the same upload on disk | Every file is checked before anything is stored |
| File names were stored as uploaded; a 300-character name ended in a 500 | Cleaned and shortened |
| No concurrency control: two handlers could both approve, a correction could race an approval | Optimistic version on the claim, 409 on conflict; the UI sends the version it showed |
| Unreadable files failed three retries and ended in the dead-letter list | Checked at ingest; NEEDS_INFO with a request to the client |
| A failed enqueue (Redis down) turned a committed upload or approval into a 500 | Logged; the worker's sweep re-enqueues claims that stopped moving |
| The worker exited for good when Redis went away | Supervisor with backoff (`make worker`) |
| Model-server outages burned all three retries in 15 seconds | Infrastructure errors wait 60 and 120 s; handlers can retry a failed claim |
| A known name was missed when written surname first with a comma, as an initial, across a line break, declined, or as a surname after a form of address | Name variants and Slovak/Czech case forms in the PII guard |
| A cut-off image passed the check when WeasyPrint had been imported in the same process | The check sets Pillow's truncated-image flag itself |
| The login form could send the password as a query parameter before the page hydrated | `method="post"` |
| Login allowed unlimited guesses and answered an unknown user faster than a wrong password | Rate limit per account; same scrypt work either way |
| Field rows were buttons containing buttons; tertiary text had 3.4:1 contrast; the page viewer could not be scrolled with the keyboard | Label buttons with `aria-pressed`, darker tertiary ink (4.9:1), focusable viewer region, reduced motion respected |
