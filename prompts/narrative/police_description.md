---
version: 1
description: Incident description in a police theft report (synthetic data generator)
---
## system
You write the incident description of a police theft report as recorded by the officer. Write in the requested language only, third person, factual.

## user
Language: {{ language }}
Write 2 to 4 sentences about how the theft happened. Do not list item values, names or dates. Do not add a heading.

Facts:
{{ facts }}
