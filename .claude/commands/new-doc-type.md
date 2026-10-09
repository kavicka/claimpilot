---
description: Scaffold a new document type end to end
argument-hint: <doc_type_name>
---
Add the document type `$ARGUMENTS`:

1. Add it to `DocType` in `packages/claimpilot_core/src/claimpilot_core/domain.py`.
2. Add its extraction schema in `packages/claimpilot_core/src/claimpilot_core/schemas/documents.py`,
   every field a string as printed plus a description, and register it in `SCHEMAS`.
3. Add a Jinja2 template in `data/generator/src/claimpilot_datagen/templates/` and a generator piece
   that writes ground truth for every field.
4. Add `prompts/extraction/$ARGUMENTS.md` (version 1).
5. Write failing tests first: generator invariants, schema round-trip, ground-truth completeness.
6. Make them pass, regenerate the dataset, run `/eval extraction`.
