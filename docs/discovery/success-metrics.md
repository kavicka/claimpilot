# Success metrics

What "better" means for a pilot, and what to measure before it starts. Baselines come from the claims
team; ClaimPilot's own numbers come from the eval reports.

| Metric | Definition | Baseline to collect | Pilot target (hypothesis) |
| --- | --- | --- | --- |
| Handling time per claim | Minutes of handler work from opening to decision | Time study on 30 claims | −40 % on fast_track and standard |
| Time to decision | Calendar days from complete documents to decision | Core system timestamps | −30 % |
| Straight-through share | Claims a handler approves with no field corrected | n/a today | ≥ 35 % of medical claims under 500 EUR |
| First-request completeness | Claims where one information request was enough | Core system | +20 percentage points |
| Payout accuracy | Payouts matching a second handler's calculation | Audit sample | ≥ 99 % |
| Fraud referral recall | Confirmed fraud cases that were referred | Fraud team records | No drop against today |
| Handler trust | Share of fields handlers check against the source | Observation | Falls over the first month |

Guardrail: the system never pays or rejects on its own. Every decision has a handler and an audit entry.
