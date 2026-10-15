# Deploying to AWS

ClaimPilot runs locally on Ollama (Phase 1). This page covers the AWS deployment (Phase 2):
what it creates, what it needs, the one command that deploys it, and how to remove it. The design
decisions are in ADR-009 (infrastructure), ADR-010 (Claude on Bedrock, masked scans) and ADR-011
(embeddings); the cost estimate is in [`governance/cost.md`](governance/cost.md).

Status: nothing here has been applied to an AWS account yet. The Terraform passes `validate`,
mocked `terraform test`, tflint and checkov; the container images build and start with a
read-only root file system; the Bedrock adapter is tested against the real Anthropic SDK with a
mocked HTTP transport. The first `make deploy` is the first test against AWS itself.

## What gets created

All in eu-central-1, all named `claimpilot-<environment>`:

| Part | What | Notes |
| --- | --- | --- |
| Network | VPC, 2 public and 2 private subnets, no NAT gateway | Private subnets have no route out of the VPC |
| Endpoints | bedrock-runtime, ecr.api, ecr.dkr, logs, secretsmanager, xray, S3 gateway (textract when chosen) | The only ways out of the private subnets |
| Load balancer | ALB with WAF (AWS managed rules, rate limit) | Reachable from `allowed_cidrs` only; HTTPS when `certificate_arn` is set |
| Services | ECS Fargate, ARM64: ui, api, worker, core-mock, mcp | Service Connect names; read-only root file systems |
| Data | RDS PostgreSQL 17 (pgvector), Valkey, EFS | Encrypted with one KMS key; TLS enforced |
| Secrets | Secrets Manager: app secrets, queue URL; RDS-managed DB password | PII vault key never in Terraform state |
| Images | ECR, one repository per service | Immutable tags (the git commit), scan on push; the ADOT collector through a pull-through cache from ECR Public |
| Traces | ADOT sidecar next to the api and the worker, X-Ray | Step, model, tokens, latency; no prompt or response text. Filter one claim with `annotation.claimpilot_claim_id` |
| Cost guard | AWS Budgets on the whole account, email at 80 % actual and 100 % forecast | `budget_monthly_usd`, default 400; use an account for this stack |

## Before the first deploy

1. **An AWS account for this stack** (the budget watches the whole account) and credentials with
   administrator rights on your machine
   (`aws configure sso` or environment variables). `aws sts get-caller-identity` must work.
2. **Bedrock model access** in eu-central-1 (Bedrock console, Model access) for Claude Haiku 5.5,
   Sonnet 5.5 and Opus 5.5, and Cohere Embed Multilingual v3. The worker calls the Claude models
   through the EU inference profiles `eu.anthropic.claude-*-5-5`, which route only to EU Regions.
3. **Optional, only for `ocr_engine = "textract"` in `terraform.tfvars`:** an AWS Organizations AI services opt-out policy
   (`{"services":{"default":{"opt_out_policy":{"@@assign":"optOut"}}}}`). Without it, Textract may
   keep document inputs to improve the service.
4. **Tools:** terraform 1.10 or newer, AWS CLI v2, Docker with buildx, jq, uv.
5. **Variables:** copy `infra/terraform/terraform.tfvars.example` to `terraform.tfvars` and set
   `allowed_cidrs` (your IP), `alert_email`, and `certificate_arn` if you have an ACM certificate.
6. **A clean git tree:** images are tagged with the commit id.

## Deploy

```bash
make deploy
```

`scripts/deploy/deploy.sh` runs these steps, each safe to repeat:

1. Creates the state bucket once per account (`infra/terraform/bootstrap`, KMS-encrypted,
   versioned, S3 native locking) and writes `infra/terraform/backend.hcl`.
2. Creates the image repositories and the empty application secret.
3. Generates the application secrets (PII vault key, session secret, demo password, intake and
   MCP tokens) and pipes them into Secrets Manager. They do not pass through Terraform, the
   terminal or process arguments. An existing value is left alone.
4. Builds the five images for linux/arm64 and pushes them, skipping tags already in ECR. The
   worker image loads every model once at build time (`claimpilot-prefetch`) and checks the loads
   again offline: the task has no internet route.
5. Applies the rest of the stack on that image tag.
6. Runs the migration task (`alembic upgrade head`) and stops if it fails.
7. Restarts the api and the worker, and waits until all services are stable.

On the worker's first start it builds the coverage index from the policy terms with Cohere
embeddings.

It prints the URL and the command that reads the demo password:

```bash
aws secretsmanager get-secret-value --region eu-central-1 --secret-id <app_secret_arn> \
  --query SecretString --output text | jq -r .DEMO_PASSWORD
```

Upload demo claims the way the local demo does, with the deployed URL and the intake token from
the same secret:

```bash
CLAIMPILOT_API_URL=<url> CLAIMPILOT_INTAKE_TOKEN=<INTAKE_TOKEN> uv run claimpilot-eval seed --split dev --n 5
```

## Deploy from GitHub Actions

`.github/workflows/deploy.yml` runs the same script on a manual trigger, on an ARM runner, in the
`production` environment (add a required reviewer there). It holds no AWS keys: it assumes a role
through OIDC.

1. Apply the bootstrap once with your repository: `terraform -chdir=infra/terraform/bootstrap apply
   -var github_repository=<owner>/<repo>`. It creates the OIDC provider, the deploy role (trusted
   only for the `production` environment) and the eval role (Bedrock invoke only, trusted for
   pull requests).
2. Set the repository variables listed at the top of the workflow from the bootstrap outputs.
3. Actions, deploy, Run workflow.

`.github/workflows/eval-live.yml` runs doc_type, extraction and routing against Bedrock on pull
requests that change `prompts/` or `config/providers.cloud.yaml`, when `AWS_EVAL_ROLE_ARN` is set.
It reports and does not block: there is no Bedrock baseline yet.

## Check without an AWS account

```bash
make infra-check
```

Runs `terraform fmt -check`, `validate`, `terraform test` with mocked providers (9 runs: no route
out of the private subnets, encryption at rest and in transit, Bedrock only from the worker and
only in EU Regions, read-only containers, least secrets per task, demo and HA sizes, uploads past
the WAF, a tracing sidecar that cannot stop the app, Textract only when chosen), tflint, and
checkov (0 failed checks; each skip names its reason in the code). CI runs the same job.

## Operate

- **Logs:** CloudWatch log groups `/claimpilot/<environment>/<service>`, 30 days. They hold claim
  ids and step names, no personal data.
- **Worker size:** `worker = { cpu, memory, count }`. Set `count = 0` to stop paying for the
  worker while nobody uses the demo; claims wait in the queue.
- **High availability:** `ha = true` for Multi-AZ RDS, two Valkey nodes, endpoints in both AZs and
  two ui and api tasks.
- **Rotating the PII vault key** re-encrypts `pii.vault`; it is a migration, not a Secrets Manager
  rotation. Other app secrets can be changed in Secrets Manager followed by a service restart.

Hardening left for a production account: IAM database authentication instead of the password,
an S3 storage backend instead of EFS, HTTPS with a certificate (required, not optional), a
decision on Bedrock invocation logging (off by default, and it would store redacted prompts),
and masking checked on real handwritten documents (ADR-010).

## Remove

```bash
make destroy
```

Turns off deletion protection on the database and the load balancer, then destroys the stack. It
leaves the state bucket and a final database snapshot (`claimpilot-<environment>-final`). The
secrets are deleted at once, the PII vault key with them, so the snapshot's `pii.vault` can no
longer be decrypted; the KMS key that encrypts the snapshot enters a 30-day deletion window. A
production stack should keep a recovery window on the secrets (`secrets.tf`).
