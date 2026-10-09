# Decision table (draft)

Routing and coverage rules written so a claims manager can check them line by line. The executable
version lives in `config/routing.yaml` and `data/policies/products.yaml`; this table must match them.

## Routing (first matching row wins, top to bottom)

| # | Condition | Queue | Why |
| --- | --- | --- | --- |
| R1 | Same invoice file (hash) or same invoice number already used in another claim | fraud_review | VPP A13.4 |
| R2 | Event date inconsistent across documents by more than 2 days | fraud_review | Fraud signal |
| R3 | Event within 3 days after the policy was concluded (issue date, not start date: a trip-day-1 event under a policy bought weeks earlier is normal) | fraud_review | Fraud signal |
| R4 | Required document missing | NEEDS_INFO (no queue) | VPP A13.2, A13.3 |
| R5 | Claimed total above 3,000 EUR | senior | Authority limit |
| R6 | Medical or accident claim whose medical report mentions a possible exclusion (alcohol, extreme sport, pre-existing condition) | senior | Needs judgement; a known reason on a cancellation is decided in coverage (A9.4) |
| R7 | Cancellation claim | standard | Always needs a reason check |
| R8 | All extracted fields grounded, confidence ≥ 0.9, total ≤ 500 EUR, no rule hit | fast_track | Straight-through candidate |
| R9 | Anything else | standard | |

Thresholds are hypotheses to validate (interview Q8, Q9).

## Coverage (per claimed item)

| Coverage | Covered when | Payout rule | Not covered when |
| --- | --- | --- | --- |
| Medical | Acute illness or injury during the trip (A4.1) | Sum of items, minus one deductible per event, capped by limit (A4.3); dental capped by sublimit (A4.4) | Pre-existing condition (A5.1), planned treatment (A5.2), alcohol (A11.2), uninsured extreme sport (A11.3), outside period or trip (A3.2, A3.3) |
| Accident | Fracture confirmed by a medical report (A6.1) | Fixed fracture benefit per product, once per event (A6.2) | Alcohol (A11.2), uninsured extreme sport (A11.3) |
| Luggage | Lost by carrier, stolen or damaged (A7.1) | Per-item limit, valuables capped at 30 % of the luggage limit, total limit, one deductible (A7.2, A7.3) | Unattended valuables (A7.5), cash and documents (A7.6) |
| Delay | Carrier delay over 12 hours (A8.1, A8.3) | Receipts for essentials up to the limit (A8.2) | Delay ≤ 12 h; Basic product |
| Cancellation | Illness, injury, death of a relative, property damage before departure (A9.1) | 80 % of the cancellation fee up to the limit (A9.2) | Reason known at purchase (A9.4); Basic product |

Foreign currency is converted at the fixed ECB snapshot named in the contract (A12.1).
