# ADR-010: Claude on Bedrock through the EU profiles; scans as masked images

Status: accepted, 2026-10-15

## Decision
- In the AWS deployment, Claude 5.5 models on Amazon Bedrock do the model work
  (`config/providers.cloud.yaml`): Haiku for document typing, coverage mapping and submission
  fixes; Sonnet for extraction, routing review, coverage verdicts and summaries; Opus answers when
  Sonnet declines a request. The eval judge stays a local model of another family.
- Calls go to `bedrock-runtime` in eu-central-1 with the EU inference profiles
  (`eu.anthropic.claude-*-5-5`), through the Anthropic SDK's Bedrock client (SigV4, task role).
- Text calls carry redacted text only, as in Phase 1 (ADR-003).
- Scans and photos go to Claude as page images with personal data blacked out
  (`ingest/mask.py`), next to the redacted OCR text. Masking covers every text block that holds a
  value the claim's redactor knows or a pattern match, and every line of text that RapidOCR's
  detector finds outside the parsed blocks. A page whose OCR read under 40 characters, or a
  personal value without a position, means the images are not sent and the document takes the
  text path.

## Why
- In Frankfurt, AWS documents the 5.5 models only through `bedrock-runtime` with an `eu.` or
  `global.` profile; neither Bedrock Mantle nor a plain in-Region call serves them
  (`docs/research/aws-bedrock-facts.md`, section 2). The `eu.` profile keeps processing in six EU
  Regions; `global.` would not.
- Bedrock does not train on prompts and does not share them with Anthropic; Sonnet, Haiku and
  Opus 5.5 have no forced retention (only Fable 5 and 5.1 do). Invocation logging is off unless
  turned on.
- The vision path is why scans reach 97.6 % on critical fields locally against 81.1 % through OCR
  text. Masking keeps most of that without sending a name or a birth number.
- A masking check that trusts the parser alone failed: the first masking eval found 5 personal
  values readable on 3 of 39 scans, all in letterheads and forms that Docling had filed as
  pictures. The independent text detector closed it, and the parser now reads that text too.

## Consequences
- `masking` eval (local only, macOS): Apple Vision OCR reads the masked dev scans again. Result
  on 2026-10-16: 0 personal values readable on 39 documents, 0 refused, critical values readable
  on 143/145 masked against 143/145 unmasked. Gate: `personal_values_visible` must be 0.
- The first version left dates of birth readable ("geb. 01.11.1988" on a medical report): the
  ground truth did not list them as personal data, so neither the guard nor the eval looked for
  them. A demo screenshot showed it. Dates of birth are now an entity of their own (`<DOB_1>`),
  found after their label in the claim languages, paired across OCR blocks, and derived from the
  birth number on the claim form; the ground truth lists 95 of them.
- Handwriting that the detector misses would stay visible. The synthetic scans have none, so the
  eval cannot measure this gap; it needs real samples before production.
- Cloud extraction quality is unmeasured until a Bedrock account runs the evals
  (`.github/workflows/eval-live.yml`). Cassettes keep Bedrock responses apart from Ollama ones.
- Claude 5.5 rejects non-default temperature and seed; determinism in evals comes from cassettes.
  JSON comes from structured outputs (`output_config.format`), not a forced tool choice.
- A refusal without a fallback raises `ModelRefusalError`, and the claim goes to a handler.
