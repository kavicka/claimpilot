# Human oversight

The system prepares; a person decides.

| The system may | The system may not |
| --- | --- |
| Read documents, extract fields, flag missing documents | Approve, reject or pay a claim |
| Route a claim to a queue and say why | Change a claim after a handler approved it |
| Recommend covered or not covered per item, citing clauses | Contact the client without a handler |
| Calculate the payout | Submit anything a handler did not approve |
| Draft letters and summaries | Hide its rule hits, confidence or sources |

- Every decision is a handler action through the state machine (`claimpilot_core.state_machine`);
  the system actor has no transition to APPROVED or REJECTED, and a test proves it.
- Claims in the senior and fraud-review queues need a senior handler for every decision (approve, reject, request information). Only a senior handler can erase a claim.
- The MCP server exposes read-only tools; there is no approve or submit tool.
- Every action and every field correction lands in the audit log with the user.
- A correction made after the assessment blocks approval until the handler reassesses: routing,
  payout and letters are computed again from the corrected fields.
- A handler approves what they saw: every action carries the claim version their page showed, and
  the api refuses it (409) if the claim changed since, for example after another handler's
  escalation or correction.
- Corrections feed the golden dataset, so the next eval run measures what handlers had to fix.
