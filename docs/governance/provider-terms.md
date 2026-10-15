# Model provider terms

Read on 2026-10-15; sources and quotes in `docs/research/aws-bedrock-facts.md`.

| Provider | Phase | Training on inputs | Retention of prompts | Where it runs | Source |
| --- | --- | --- | --- | --- | --- |
| Ollama (local models) | 1 | No: models run on the machine, nothing leaves it | Only what ClaimPilot itself stores (Langfuse, cassettes), all tokenized | The machine | Local deployment |
| Amazon Bedrock, Claude Haiku / Sonnet / Opus 5.5 | 2 | No: "not used to improve the base models and is not shared with any model providers"; Anthropic has no access to the inference infrastructure or to prompts | Depends on the account's data retention mode. Under `default`, AWS may keep data for abuse prevention; the provider does not receive it. Forced 30-day retention applies only to Fable 5 and 5.1, which ClaimPilot does not use. Invocation logging is off unless turned on | eu-central-1 with the `eu.` inference profiles: processed in eu-central-1, eu-north-1, eu-south-1, eu-south-2, eu-west-1 or eu-west-3. CloudTrail records the Region of each call (`inferenceRegion`) | Bedrock data protection, data retention, cross-Region inference, model cards (S1–S5, S11–S15) |
| Amazon Bedrock, Cohere Embed Multilingual v3 | 2 | As above | As above | In-Region, eu-central-1 | S11, S21 |
| Amazon Textract (optional OCR) | 2 | **Yes, unless opted out**: Textract "may store and use document and image inputs" to improve AWS services | Inputs may be stored, also in another Region, until the AI services opt-out policy is set; opting out deletes them | eu-central-1 | Textract FAQ, Organizations AI opt-out policy (S29–S32) |

Before the first deploy:

- Set the account's Bedrock data retention mode to `none` if the insurer wants no abuse-prevention
  copies; ask Anthropic about zero data retention for Claude if needed.
- Keep Textract off (`ocr_engine = docling`, the default) unless the AI services opt-out policy is in
  place.
- Keep the PII guard in enforcing mode: text calls carry tokens, scans go as masked images (ADR-010).
