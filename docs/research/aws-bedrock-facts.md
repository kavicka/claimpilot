# AWS / Bedrock fact sheet for the eu-central-1 deployment plan

All sources were read on **2026-10-15**. Every fact cites a source ID; the full URLs are in the [Sources](#sources) list at the end.
docs.aws.amazon.com pages were read through their official Markdown version (the same URL with `.md`). JS-rendered price tables on aws.amazon.com were read in a browser with the Region set to **Europe (Frankfurt)**.
Prices are in USD and exclude tax.

> **The biggest finding: the planned Claude call path is not documented for Frankfurt.**
> AWS documents no in-Region availability on the `bedrock-mantle` endpoint in eu-central-1 for `anthropic.claude-sonnet-5-5`, `anthropic.claude-haiku-5-5` or `anthropic.claude-opus-5-5` [S11][S12][S13][S14].
> On mantle, the model cards list cross-Region profiles as "N/A" [S12–S14]. In eu-central-1, these models are documented only through the **`bedrock-runtime`** endpoint with an `eu.` (Geo) or `global.` inference profile [S11].
> So `AnthropicBedrockMantle` + `https://bedrock-mantle.eu-central-1.api.aws/anthropic/` + `anthropic.claude-sonnet-5-5` is **not** a documented combination. The documented EU-only path is described in section 2.

---

## 1. Amazon Bedrock data handling

| Question | Finding | Src |
|---|---|---|
| Are prompts and outputs used to train models? | "your content is not used to improve the base models and is not shared with any model providers" | S18, S19 |
| Does Anthropic get access to them? | Bedrock runs models in per-provider "Model Deployment Accounts" owned by the Bedrock team. Providers "don't have access to Amazon Bedrock logs or to customer prompts and completions". | S1 |
| Who runs Claude in Bedrock? | AWS-managed infrastructure with zero operator access ("Anthropic personnel have no access to the inference infrastructure"). Data handling is governed by Amazon Bedrock. | S15 |
| Are prompts and outputs stored? | This depends on the **data retention mode** (`none` < `default` < `aws_review` < legacy `provider_data_share`). Under `none`, nothing goes to durable storage and "Chat Completions and Messages requests are never retained". Under `default`, the model's own policy applies: "AWS may retain the data for safety and abuse-prevention purposes. The model provider does not receive it." | S2 |
| Which Claude models force retention? | Only models that require `aws_review`: currently **Claude Fable 5 and 5.1**. Their traffic is kept up to 30 days and may get human review by AWS. The abuse-detection page lists no retention for Sonnet, Haiku or Opus 5.5. | S2, S3 |
| How is the retention mode set? | Per Region, at account or project level, through the API (`PUT /v1/data_retention` on mantle, `PUT /data-retention` on the control plane). There is no console UI at launch. New accounts default to `inherit`, which falls back to the model default. | S2 |
| Zero data retention (ZDR) for Claude | ZDR eligibility for Claude models "is managed by Anthropic" through your Anthropic account representative. | S2 |
| Where is data processed: in-Region | "In-Region: Your requests never leave the AWS Region you specify." | S11 |
| Where is data processed: Geo (`eu.`) | Requests stay inside the geography, but "input prompts and output results might move outside of your source Region". If data is stored for abuse detection, it is stored in the **destination** Region. Traffic stays on the AWS network and is encrypted between Regions. | S4, S5 |
| EU profile from eu-central-1 | Claude Sonnet/Haiku/Opus 5.5 `eu.` profile, source eu-central-1 → destinations **eu-central-1, eu-north-1, eu-south-1, eu-south-2, eu-west-1, eu-west-3**. Call `GetInferenceProfile` to get the current routing. | S12, S13, S14 |
| Global profile (`global.`) | Routes to "any supported AWS commercial Region worldwide". It is about 10% cheaper. AWS recommends Geo instead when you have data-residency requirements. | S4 |
| Audit trail | CloudTrail logs cross-Region requests in the source Region. The field `additionalEventData.inferenceRegion` shows where each request was processed. | S4 |
| Does mantle keep processing in the chosen Region? | **UNCONFIRMED** for eu-central-1. The facts found: mantle is a "Region-specific" endpoint; it uses the same Mantle inference engine as bedrock-runtime; and it is available in eu-central-1 [S7][S8]. But the Claude 5.5 models are not listed as available on mantle in eu-central-1 [S11]. | S7, S8, S11 |
| Model invocation logging | **Disabled by default (opt-in).** Destinations are CloudWatch Logs and/or S3, and "only destinations from the same account and Region are supported". Logs are kept until you delete the logging configuration. It is **only supported on `bedrock-runtime`**; calls on `bedrock-mantle` "are not currently captured". | S6 |
| GDPR / DPA | Bedrock docs point to the AWS GDPR Center. The AWS DPA and the 2021 SCCs are part of the AWS Service Terms and "will apply automatically" to transfers to third countries. "customers can use Bedrock in compliance with the GDPR". | S1, S19, S20 |
| Explicit "EU data residency" statement for Bedrock | **UNCONFIRMED** as a dedicated statement. The closest is the Geo CRIS wording: data stays "within geographic boundaries (such as US, EU, and APAC)". | S4, S5 |

## 2. Model availability in eu-central-1

| Model | Model ID | EU Geo profile ID | In-Region runtime | In-Region mantle | Geo (`eu.`) runtime | Global runtime | Src |
|---|---|---|---|---|---|---|---|
| Claude Sonnet 5.5 | `anthropic.claude-sonnet-5-5` | `eu.anthropic.claude-sonnet-5-5` | no | no | **yes** | yes | S11, S12 |
| Claude Haiku 5.5 | `anthropic.claude-haiku-5-5` | `eu.anthropic.claude-haiku-5-5` | no | no | **yes** | yes | S11, S13 |
| Claude Opus 5.5 | `anthropic.claude-opus-5-5` | `eu.anthropic.claude-opus-5-5` | no | no | **yes** | yes | S11, S14 |

- **Mantle availability for these models:**
  - Sonnet 5.5 and Haiku 5.5: in-Region only in us-gov-west-1.
  - Opus 5.5: us-east-1, ap-southeast-4 and us-gov-west-1.
  - The only EU in-Region option is Opus 5.5 on **runtime** in eu-west-2 (London).

  Source: [S11].
- **Endpoint URLs** [S9][S12]:
  - Messages API on runtime: `https://bedrock-runtime.{region}.amazonaws.com/anthropic`
  - Messages API on mantle: `https://bedrock-mantle.{region}.api.aws/anthropic/v1/messages`
- **AWS recommendation:** AWS recommends `bedrock-runtime` for new applications. It supports IAM, invocation logging and cross-Region inference [S7][S9].
- **Python SDK usage on runtime:** the AWS sample uses `Anthropic(base_url="https://bedrock-runtime.<region>.amazonaws.com/anthropic", api_key=<token from aws-bedrock-token-generator>)` with a profile ID as `model` [S9].
- **`AnthropicBedrockMantle` client:** documented by Anthropic for mantle, with model IDs such as `anthropic.claude-opus-5-5`. It signs requests with SigV4. A plain `Anthropic` client pointed at `.../anthropic` supports bearer tokens only [S15].
- **Anthropic's region table:** lists eu-central-1 as "Global, EU", without "In-region only". Its regional (non-global) endpoints carry a 10% premium [S15].
- **Model access:** Anthropic says Sonnet, Haiku and Opus 5.5 access criteria are set by Bedrock ("See Access"), so check the console [S15].
- **Model details:**
  - Sonnet 5.5: launched 2026-09-28, 1M context [S12].
  - Haiku 5.5: launched 2026-10-07, 1M context [S13].
  - Opus 5.5: launched 2026-09-22, 1M context [S14].

**Documented EU-only path from Frankfurt:** `bedrock-runtime.eu-central-1` + `eu.anthropic.claude-*-5-5`. Data is processed in one of the six EU destination Regions listed in section 1.

## 3. Bedrock on-demand prices for Claude (Region = Europe (Frankfurt), per 1M tokens)

| Model / tier | Input | Output | 5m cache write | 1h cache write | Cache read | Batch | Src |
|---|---|---|---|---|---|---|---|
| Sonnet 5.5, Global | $2.00 | $10.00 | $2.50 | $4.00 | $0.10 | N/A | S17 |
| Sonnet 5.5, Geo/In-Region (`eu.`) | **$2.20** | **$11.00** | $2.75 | $4.40 | $0.11 | N/A | S17 |
| Haiku 5.5, Global | $0.10 | $0.50 | $0.125 | $0.20 | $0.01 | N/A | S17 |
| Haiku 5.5, Geo/In-Region (`eu.`) | **$0.11** | **$0.55** | $0.1375 | $0.22 | $0.011 | N/A | S17 |
| Haiku 5.5 Long Context (>100k prompt), Geo | $0.55 | $2.75 | $0.6875 | $1.10 | $0.055 | N/A | S17 |
| Opus 5.5, Global | $4.00 | $20.00 | $5.00 | $8.00 | $0.20 | N/A | S17 |
| Opus 5.5, Geo/In-Region (`eu.`) | **$4.40** | **$22.00** | $5.50 | $8.80 | $0.22 | N/A | S17 |

- **Comparison with Anthropic's own prices.** The **Global** Bedrock prices match Anthropic first-party exactly:
  - Sonnet 5.5: $2/$10; cache read $0.10.
  - Haiku 5.5 (≤100k-token prompt): $0.10/$0.50.
  - Opus 5.5: $4/$20.

  The **Geo/In-Region (EU)** rows are **+10%**, which matches Anthropic's statement that "Regional endpoints carry a 10% pricing premium" [S15][S16][S17].
- **Price notes on the Bedrock page:**
  - "Starting October 7, 2026, cache read pricing for Claude Sonnet 5.5 is reduced by 50%". The values above are the current displayed ones.
  - Batch is shown as N/A for all three 5.5 models.

  Source: [S17].
- **Billing:** Claude is billed through AWS Marketplace, so charges appear under the model provider in Cost Explorer [S12].
- **Pricing the eu-central-1 mantle path:** **UNCONFIRMED** (not separately listed; the pricing table has only Global and "Geo and In-region" rows) [S17].

## 4. Embeddings for multilingual retrieval (sk, de, it, hr, cs, en)

| Model | Model ID | eu-central-1 | Price / 1M input tokens (Frankfurt) | Dimensions | Languages | Src |
|---|---|---|---|---|---|---|
| Cohere Embed Multilingual v3 | `cohere.embed-multilingual-v3` | **In-Region yes**; Geo/Global not supported | **$0.10** | fixed **1024** | "100+ languages"; 512-token context | S11, S17, S21, S25 |
| Cohere Embed v4 | `cohere.embed-v4:0` (Geo `eu.cohere.embed-v4:0`) | In-Region **no**; Geo + Global yes. EU destinations from eu-central-1 are the same six Regions as for Claude. | **$0.12** | 256 / 512 / **1024** / 1536 (default 1536, set `output_dimension`) | not listed on the AWS card; 128K context | S11, S17, S22, S26 |
| Amazon Titan Text Embeddings V2 | `amazon.titan-embed-text-v2:0` | **In-Region yes**; Geo/Global not supported | **$0.20** (batch $0.10) as displayed on the pricing page | **1024 (default)** / 512 / 256 | "English (100+ languages in preview)". The list includes Slovak, German, Italian, Croatian, Czech and English. Cross-language queries "will return sub-optimal results". | S11, S17, S23, S24 |

- **For a strict in-Region 1024-dim setup in Frankfurt:** Embed Multilingual v3 (1024 is native) and Titan V2 (`dimensions: 1024`) both qualify. Embed v4 needs the `eu.` profile (cross-Region within the EU) [S11].

## 5. Amazon Textract (eu-central-1)

| Item | Finding | Src |
|---|---|---|
| Availability | Endpoint `textract.eu-central-1.amazonaws.com` (and `.api.aws`) is listed for Europe (Frankfurt). | S27 |
| DetectDocumentText | $1.50 per 1,000 pages (**$0.0015/page**) for the first 1M pages/month; $0.60 per 1,000 after that | S28 |
| AnalyzeDocument Tables + Forms | $15.00 + $50.00 = **$65 per 1,000 pages ($0.065/page)** for the first 1M; $10 + $40 = $50 per 1,000 after. Tables only: $15. Forms only: $50. | S28 |
| Content use | "Amazon Textract may store and use document and image inputs ... to improve and develop the quality of Amazon Textract and other Amazon machine-learning/artificial-intelligence technologies." | S29 |
| Region of storage | Content is "stored at rest in the AWS region where you are using Amazon Textract". **Unless you opt out**, some of it "may be stored in another AWS region" for service improvement. | S29 |
| Opt-out | Use the AWS Organizations **AI services opt-out policy**. Textract is a supported service, with key `textract` or `default` for all services, e.g. `{"services":{"default":{"opt_out_policy":{"@@assign":"optOut"}}}}`. Opting out deletes the historical content stored for improvement. The preference is recorded in every Region. | S30, S31, S32 |
| Deletion | You can request deletion of stored inputs through AWS Support. | S29 |
| Bedrock in the opt-out list? | `bedrock` is not among the valid policy keys. Bedrock's no-training statement in section 1 covers it instead. | S32, S18 |

## 6. Infrastructure prices (Region = Europe (Frankfurt), on-demand)

| Service | Price | Src |
|---|---|---|
| Fargate Linux/x86 | **$0.04656 per vCPU-hour**, **$0.00511 per GB-hour** | S33 |
| Fargate Linux/ARM (Graviton) | **$0.03725 per vCPU-hour**, **$0.00409 per GB-hour** (about 20% below x86) | S33 |
| RDS PostgreSQL db.t4g.small | **$0.037/h** Single-AZ; $0.074/h Multi-AZ (one standby) | S34 |
| RDS PostgreSQL db.t4g.medium | **$0.074/h** Single-AZ; $0.149/h Multi-AZ (one standby) | S34 |
| RDS T4g CPU credits | T4g runs in Unlimited mode; extra credits cost $0.075 per vCPU-hour (all Regions) | S34 |
| pgvector on RDS | Supported. Latest minors 14.24, 15.19, 16.15, 17.11 and 18.6 ship **pgvector 0.8.2**; 13.23 ships 0.8.0; 12.x up to 0.7.3. PostgreSQL 19 is RC/beta only (0.8.2). | S35 |
| ElastiCache Valkey, smallest node | **cache.t4g.micro $0.0144/h** (0.5 GiB); cache.t4g.small $0.0288/h | S36 |
| ElastiCache Redis OSS, smallest node | cache.t4g.micro $0.018/h | S36 |
| NAT gateway | **$0.052 per hour + $0.052 per GB processed** | S37 |
| Public IPv4 address (e.g. the NAT EIP) | $0.005 per hour. This comes from the page's IPv4 table/example and is not Region-filtered. | S37 |
| VPC interface endpoint (PrivateLink) | **$0.012 per endpoint per AZ per hour**, plus $0.01/GB for the first 1 PB | S38 |
| KMS customer-managed key | **$1/month** per key, prorated hourly. The first and second rotation add $1/month each. Requests cost $0.03 per 10,000 (Frankfurt). Free tier: 20,000 requests/month. AWS-managed keys have no monthly fee. | S39 |
| Secrets Manager | **$0.40 per secret per month** (prorated) + $0.05 per 10,000 API calls. The page shows a single global price, with no Region selector. | S40 |

## 7. GitHub Actions OIDC to AWS

| Item | Value | Src |
|---|---|---|
| IAM OIDC provider URL | `https://token.actions.githubusercontent.com` | S42 |
| Audience | `sts.amazonaws.com` (the console prompt: "For **Audience**, choose `sts.amazonaws.com`") | S41 |
| Trust-policy conditions | `token.actions.githubusercontent.com:aud = sts.amazonaws.com` and `token.actions.githubusercontent.com:sub = repo:<org>/<repo>:ref:refs/heads/<branch>`. AWS recommends limiting the role to specific repos or branches. | S41 |
| Required claim | For this shared provider, IAM requires a condition on `sub` or `job_workflow_ref`. | S42 |
| Workflow permissions | `id-token: write` (plus `contents: read`) | S43 |
| Action | `aws-actions/configure-aws-credentials` with `role-to-assume`, `aws-region` and optional `role-session-name` | S43 |
| Current major version | **UNCONFIRMED** from an official AWS page. The newest AWS page found (ECS blog, published 2026-03-10) uses `@v5` [S43]; the CloudWatch docs page uses `@v4` [S44]. The authoritative source is the action's GitHub releases, which is not on the allowed domain list. | S43, S44 |

## What I could not confirm

1. **Data residency on mantle in eu-central-1.** Whether the `bedrock-mantle` endpoint in eu-central-1 serves Claude Sonnet/Haiku/Opus 5.5 at all, and if so whether it stays in-Region. The AWS availability tables say no in-Region mantle support there, and mantle has no `eu.` profile.
2. **A Bedrock-specific EU data-residency statement.** I found only the Geo-CRIS "within geographic boundaries" wording and the generic GDPR/DPA pages.
3. **Price of a mantle call from eu-central-1** (not listed separately).
4. **The current major version of `aws-actions/configure-aws-credentials`.** AWS pages show v4 and v5; GitHub was out of scope.
5. **Titan V2 at $0.20/1M in Frankfurt.** This is the value the pricing page displays. I did not cross-check it against another official source.
6. **Cohere Embed v4 language coverage.** It is not stated on the AWS model card.

## Sources

All read 2026-10-15.

| ID | URL |
|---|---|
| S1 | https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html |
| S2 | https://docs.aws.amazon.com/bedrock/latest/userguide/data-retention.html |
| S3 | https://docs.aws.amazon.com/bedrock/latest/userguide/abuse-detection.html |
| S4 | https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html |
| S5 | https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html |
| S6 | https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html |
| S7 | https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html |
| S8 | https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints-region-availability.html |
| S9 | https://docs.aws.amazon.com/bedrock/latest/userguide/inference-messages-api.html |
| S10 | https://docs.aws.amazon.com/bedrock/latest/userguide/models-endpoint-availability.html |
| S11 | https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html |
| S12 | https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html |
| S13 | https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-5-5.html |
| S14 | https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html |
| S15 | https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock |
| S16 | https://platform.claude.com/docs/en/about-claude/pricing |
| S17 | https://aws.amazon.com/bedrock/pricing/ |
| S18 | https://aws.amazon.com/bedrock/faqs/ |
| S19 | https://aws.amazon.com/bedrock/security-compliance/ |
| S20 | https://aws.amazon.com/compliance/gdpr-center/ |
| S21 | https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-cohere-embed-multilingual.html |
| S22 | https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-cohere-embed-v4.html |
| S23 | https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-titan-text-embeddings-v2.html |
| S24 | https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html |
| S25 | https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-embed-v3.html |
| S26 | https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-embed-v4.html |
| S27 | https://docs.aws.amazon.com/general/latest/gr/textract.html |
| S28 | https://aws.amazon.com/textract/pricing/ |
| S29 | https://aws.amazon.com/textract/faqs/ |
| S30 | https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_ai-opt-out.html |
| S31 | https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_ai-opt-out_all.html |
| S32 | https://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_policies_ai-opt-out_syntax.html |
| S33 | https://aws.amazon.com/fargate/pricing/ |
| S34 | https://aws.amazon.com/rds/postgresql/pricing/ |
| S35 | https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html |
| S36 | https://aws.amazon.com/elasticache/pricing/ |
| S37 | https://aws.amazon.com/vpc/pricing/ |
| S38 | https://aws.amazon.com/privatelink/pricing/ |
| S39 | https://aws.amazon.com/kms/pricing/ |
| S40 | https://aws.amazon.com/secrets-manager/pricing/ |
| S41 | https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html |
| S42 | https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_oidc_secure-by-default.html |
| S43 | https://aws.amazon.com/blogs/containers/automated-deployments-with-github-actions-for-amazon-ecs-express-mode/ |
| S44 | https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Service-Application-Observability-for-AWS-GitHub-Action.html |
