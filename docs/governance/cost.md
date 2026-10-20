# Cost estimate for the AWS deployment

An estimate, not a bill: nothing has run on AWS yet. Prices are on-demand list prices for
eu-central-1 read on 2026-10-15 (`docs/research/aws-bedrock-facts.md`, sections 3, 6 and 8),
in USD without tax. Token counts come from the local models' cassettes, so Claude's tokenizer may
count 10 to 30 % more on Slovak and German text.

## Fixed: the demo stack idle, per month

`ha = false`, defaults from `infra/terraform/variables.tf`, 730 hours.

| Item | Size | USD / month |
| --- | --- | --- |
| Fargate worker (ARM64) | 2 vCPU, 8 GB | 78.27 |
| Fargate api | 1 vCPU, 2 GB | 33.16 |
| Fargate ui | 0.5 vCPU, 1 GB | 16.58 |
| Fargate core-mock, erp-mock, mcp | 0.25 vCPU, 0.5 GB each | 24.87 |
| VPC interface endpoints | 6 endpoints in 1 AZ ($0.012/h each) | 52.56 |
| Container Insights (enhanced) | 626 metrics at $0.07 | 43.82 |
| Load balancer | $0.027/h, about 0.5 LCU, 2 public IPv4 addresses | 29.93 |
| RDS PostgreSQL | db.t4g.small Single-AZ, 20 GB gp3 | 29.75 |
| ElastiCache Valkey | cache.t4g.micro | 10.51 |
| WAF | 1 web ACL, 3 rules; requests negligible | 8.00 |
| ECR | 5 kept versions, about 11 GB each (the worker image is 9.2 GB with its models) | 5.50 |
| KMS | application key and state key | 2.00 |
| CloudWatch Logs | about 2 GB ingested | 1.26 |
| Secrets Manager | 4 secrets | 1.60 |
| EFS | about 2 GB of documents | 0.72 |
| X-Ray, Budgets | inside the free tier | 0.00 |
| **Total** | | **about 339** |

What moves it:

- **Worker parked** (`worker.count = 0` between demos): about 261 a month. Claims wait in the
  queue until it runs again.
- **Container Insights** is the second-largest line for a stack this small; switching it to the
  standard level or off removes most of the 43.82 (checkov's CKV_AWS_65 then needs a skip).
- **`ha = true`**: Multi-AZ RDS (+29.75), a second cache node (+10.51), endpoints in both AZs
  (+52.56), a second ui and api task (+49.74). About 481 a month.
- **Worker at 4 vCPU and 16 GB** (faster parsing): +78.27.
- **No NAT gateway** saves $0.052/h plus $0.052/GB; the endpoints that replace it cost more at
  this size (52.56 against about 38 plus traffic), and are there for the no-internet-route
  property, not for price (ADR-009).

## Variable: Bedrock per claim

Calls per claim from the dev split (40 claims, 148 documents of which 39 scans, 60 coverage
items, 111 generated texts). Prices of the EU inference profiles: Haiku 5.5 $0.11 in / $0.55
out, Sonnet 5.5 $2.20 / $11.00 per million tokens.

| Step | Model | Calls per claim | Tokens in / out per call | USD per claim |
| --- | --- | --- | --- | --- |
| Extraction, text | Sonnet | 2.7 | 2,477 / 737 | 0.0366 |
| Extraction, masked scan | Sonnet | 1.0 | about 4,000 / 818 | 0.0178 |
| Summaries and letter reasons | Sonnet | 2.8 | 538 / 194 | 0.0093 |
| Coverage verdicts | Sonnet | 1.6 | 1,054 / 121 | 0.0058 |
| Routing review | Sonnet | 0.15 | 512 / 60 | 0.0003 |
| Submission fixes | Haiku | 1.0 | 778 / 124 | 0.0002 |
| Coverage mapping | Haiku | 1.0 | 411 / 39 | 0.0001 |
| Document type | Haiku | 0.03 | 338 / 187 | 0.0000 |
| **Total** | | | | **about 0.07; 0.09 with a 30 % tokenizer margin** |

- The masked-scan row assumes one page image of about 1,500 tokens (Anthropic's
  width × height / 750 rule, after Claude scales a 1,600-pixel page to its 1,568-pixel limit) plus
  the redacted OCR text and the prompt.
- Embeddings (Cohere, $0.10 per million tokens) cost well under a cent per claim; the policy index
  is built once.
- A refusal retried on Opus 5.5 ($4.40 / $22.00) costs about twice the Sonnet call it replaces; no
  dev claim triggers one locally, so it is left out.
- Textract, if turned on, adds $0.0015 per scanned page.

At 1,000 claims a month, Bedrock adds about 70 to 90 USD to the fixed 339.

## Check it after the first deploy

- Cost Explorer, grouped by service, and by the `Project = claimpilot` tag once it is activated
  as a cost allocation tag. Claude is billed through AWS Marketplace and shows under the model
  provider; model calls carry no resource tags, which is why the budget watches the whole account.
- `pipeline_step_runs.tokens_in` and `tokens_out` per claim, against the table above.
- The budget alerts at 80 % of `budget_monthly_usd` (default 400) and when the forecast passes it.
