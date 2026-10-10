# Model provider terms

| Provider | Phase | Training on inputs | Retention of prompts | Region | Source |
| --- | --- | --- | --- | --- | --- |
| Ollama (local models) | 1 | No: models run on the machine, nothing leaves it | Only what ClaimPilot itself stores (Langfuse, cassettes), all tokenized | The machine | Local deployment |
| Amazon Bedrock | 2 | AWS states that customer data is not shared with model providers and is not used to improve the base models | To confirm before Phase 2: invocation logging is off by default and opt-in; abuse detection applies | EU region to choose (e.g. eu-central-1); confirm model availability there | [Amazon Bedrock security and privacy](https://aws.amazon.com/bedrock/security-compliance/), [Bedrock data protection](https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html), checked 2026-10-09 |

Before Phase 2: re-read both pages, record the exact model IDs and region, and keep the PII guard in
enforcing mode so only tokens leave the machine.
