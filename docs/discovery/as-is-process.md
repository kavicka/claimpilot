# As-is process (hypothesis)

Built from public descriptions of travel-claim handling and the structure of Slovak travel policy terms.
Not validated with a handler yet; each step lists the question that would confirm it.

| # | Step | Who | Time hypothesis | Where it waits | Validate with |
| --- | --- | --- | --- | --- | --- |
| 1 | Claim arrives by portal or email with scans and photos | Client | — | Client sends documents in several batches | Q3, Q6 |
| 2 | Registration: create the claim in the core system, attach files | Back office | 5–10 min | Retyping policy and personal data | Q5 |
| 3 | Completeness check against the documents the terms require | Handler | 5 min | Request letter to the client; days to weeks | Q6, Q11 |
| 4 | Read documents: invoices and reports in DE, IT, HR, EN | Handler | 10–30 min | Translation or a colleague who reads the language | Q11 |
| 5 | Coverage check: policy period, trip dates, exclusions, limits | Handler | 10 min | Looking up the right clause | Q7 |
| 6 | Payout calculation: FX, deductible, sublimits, prior payouts | Handler | 5–10 min | Exchange rate lookup | Q7, Q12 |
| 7 | Escalation of large, unclear or suspicious claims | Senior / fraud | 1–5 days | Senior's queue | Q8, Q9 |
| 8 | Decision letter to the client, payment order | Handler | 10 min | Template edits | Q13 |

Hypotheses ClaimPilot builds on:
- H1. Most handling time goes to steps 3–6 (reading, checking, calculating), not to the decision itself.
- H2. Missing documents (step 3) cause the longest waits.
- H3. Fraud signals are mostly mechanical (duplicate invoice, dates that do not line up, an event days after
  the policy was bought) and can be checked by rules.
- H4. Handlers trust a pre-filled claim only if every value links back to where it was read.
