# ADR-012: Prompt injection: detect in code, guard results in code

Status: accepted, 2026-10-16

## Decision
Every claim document is the claimant's text, so it is treated as hostile input on four layers:

1. **Keep hidden text away from models.** `ingest/hidden_text.py` reads the PDF text layer with
   PyMuPDF and marks text a reader cannot see: contrast under 1.25 against its background, font
   under 4 pt, outside the page, invisible render mode (unless it lies on an image: a scanner's OCR
   layer), fully transparent, or drawn over by a box or image. Hidden blocks stay in `doc_blocks`
   (`hidden` column) for the handler but are never typed, extracted from, grounded on or sent to a
   model.
2. **Detect and route.** `ingest/injection_signals.py` finds text that addresses an AI system,
   tells it to drop its rules, imitates role tags, our delimiters or our JSON answer, names our
   internal labels, or asks for an approval, a queue or an amount, in the six dataset languages.
   Any signal or hidden block raises routing rule R10: senior queue at least, never fast-track,
   no routing model. Later prompts (the handler summary) get the R10 hit without the planted text.
3. **Make document text inert.** `claimpilot_core.llm.untrusted` rewrites our delimiters, page
   markers and chat-template tokens inside document text and wraps every document-derived value
   in `<<<` `>>>`; each prompt that reads document text says it is data.
4. **Guard model results in code, one way only.** The routing model can only escalate. A coverage
   verdict of "covered" becomes needs_review when it cites no clause, when a medical report names
   an exclusion (alcohol, a known condition, an extreme sport the product does not include) or when
   the claim carries an injection signal. Code never makes a verdict looser.

## Why
Prompt instructions alone did not hold: on clean dev claims the coverage model already said
"covered" for an uninsured extreme sport, a known condition and a cancellation for a known reason.
An attacker only has to push the same way. Detection in code is cheap, explainable to a handler
and testable; the guards make a missed detection harmless for money and queues.

## Consequences
- A claim with a false-positive signal costs a senior handler's look. The detector has 0 false
  positives on every dev and test document; the `injection` suite gates on that.
- Obfuscated text (leetspeak, spaced letters, base64) and text outside the page content (metadata,
  annotations, form fields) are expected detector misses; the `adversarial` suite checks that they
  fail anyway.
- Not covered: a mismatch between a scan's OCR layer and its image, and forged documents whose
  printed amounts are consistent. Both are document fraud for the handler and the fraud rules.
