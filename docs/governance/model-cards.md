# Model cards

One card per pipeline step that uses a model. All models run locally in Ollama on a Mac mini M4 Pro
(48 GB); nothing leaves the machine in Phase 1. Numbers are from the dev split (40 claims) and the
held-out test split (20 claims), 2026-10-10; the reports with every failure are in `evals/reports`.

| Step | Model | Intended use | Latest numbers (dev / test) | Known failure modes |
| --- | --- | --- | --- | --- |
| Document type (fallback) | qwen3:4b-instruct | Label a document when keyword rules tie (6 % of documents) | 147/148 / 75/76 documents typed correctly, with rules | Confuses a scanned clinic invoice with a pharmacy receipt when the header is stamped over |
| Extraction (text) | qwen3:30b-a3b-instruct-2507 Q4 | Copy fields as printed from redacted text of digital PDFs, with quote and page | Critical fields 450/454 / 295/297 with the vision path on scans; field F1 96.4 % / 94.9 %; same accuracy as qwen3:14b at 2.4 times the speed | On OCR text of scans it loses values under stamps and in shifted table rows (81.1 % critical fields on dev scans), so scans go to the vision model; read one checkbox mark as belonging to the label before it |
| Extraction (vision) | qwen3-vl:8b | Read scans and photos from the page image | Dev scans: critical fields 160/164 (97.6 %), F1 92.1 %; 33 s per page (p50) | Lists invoice lines in another order; values it reads are often not in the OCR text, so their confidence is lower than their accuracy (calibration error 0.09 overall). Page images hold personal data: local providers only |
| Routing review | qwen3:14b | Second look at claims no rule decided (R9, 15 % of dev claims) | Queue right for 38/40 / 18/20 claims with the rules | Escalates to the senior queue on vague grounds (an injury it finds unusual, a sport it assumes is extreme) |
| Coverage mapping and verdicts | qwen3:14b | Map items to coverage sections; covered / not covered / needs review with cited clauses | Item verdicts 48/60 / 26/28; payouts to the cent 31/37 / 16/18 | Applies the "valuables left unattended" exclusion to luggage the airline lost; misses an extreme sport the policy does not name |
| Summaries and letter reasons | qwen3:30b-a3b-instruct-2507 Q4 | Slovak handler summary and letter reasons, German group summary, from structured facts | 0 facts outside the input in 111 dev texts; judge 4.52 / 4.56 of 5; one test summary ran over the 150-word limit | Before totals were added to the facts it summed amounts itself; the fact checker caught all 7 cases |
| Submission agent | qwen3:14b | Fix code-list mismatches after a 422 from the core system | Registered on the first try 36/37 / 18/18; 0 invented values | Asked for code lists that do not exist; the tool now answers with the list of valid names |
| Judge | gemma3:12b | Score letters and summaries on a rubric (eval only) | 30 texts scored per run | Another model family than the writer, but still lenient on style; scores are a trend, not a grade |
| Embeddings | bge-m3 | Policy clause retrieval | Deciding clause in the top 5: 45/53 / 20/24 | Exclusions rank lower than grants (5 of 8 in the top 5 on dev); article 11 is therefore always given to the coverage model |
| Reranker | BAAI/bge-reranker-v2-m3 (in-process, MPS) | Rerank 20 candidate clauses to 5 | See `retrieval` report | — |
| Names (PII) | Babelscape/wikineural-multilingual-ner (in-process, MPS) | Find person names for redaction | Names 162/162 / 88/89 redacted (with claim-wide propagation) | Missed a German doctor's name on a signature line on test; a label-based recognizer now covers it. Misses names in all-caps airline format on its own; propagation catches them |
