---
version: 2
description: Findings and treatment section of a clinic report (synthetic data generator)
---
## system
You write the "findings and treatment" section of a short clinical report from a clinic abroad. Write in the requested language only, in the terse clinical style doctors use. The findings always confirm the diagnosis you are given; never contradict it.

## user
Language: {{ language }}
Write 3 to 5 sentences: examination findings, tests done and what they showed, treatment given, recommendation. Do not mention names, dates, amounts, alcohol, sports or previous illnesses. Do not add a heading.

Facts:
{{ facts }}
