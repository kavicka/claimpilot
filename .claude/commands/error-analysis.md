---
description: Group the failures in an eval report and propose the next prompt or context change
argument-hint: <path to report json>
---
Read the eval report at `$ARGUMENTS`.

1. Group failing items by cause (wrong field mapping, format/normalization, ungrounded value, OCR
   error, missing document, model refusal). Count each group.
2. For the top 3 groups, show two concrete examples each (document, field, expected, got, source quote).
3. Propose one change per group: prompt wording, context assembly, schema description, validator or
   normalizer. Prefer code fixes for format problems.
4. Say which change to try first and how the next eval run will show whether it worked.

Do not edit prompts or code in this command.
