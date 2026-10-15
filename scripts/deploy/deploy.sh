#!/usr/bin/env bash
# From an empty AWS account to the running demo: `make deploy`.
# Needs: AWS credentials for an admin of the account, aws, terraform, docker (buildx), jq, uv,
# infra/terraform/terraform.tfvars, and Claude model access enabled in Bedrock (docs/deploy.md).
set -euo pipefail
cd "$(dirname "$0")/../.."

for cmd in aws terraform docker jq uv git; do
  command -v "$cmd" >/dev/null || { echo "missing: $cmd" >&2; exit 1; }
done
[ -f infra/terraform/terraform.tfvars ] || {
  echo "copy infra/terraform/terraform.tfvars.example to terraform.tfvars and fill it in" >&2
  exit 1
}
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "commit first: images are tagged with the commit id" >&2
  exit 1
fi
aws sts get-caller-identity --query Account --output text >/dev/null

tag=$(git rev-parse --short=12 HEAD)
tf() { terraform -chdir=infra/terraform "$@"; }

echo "== state bucket (once per account)"
if [ ! -f infra/terraform/backend.hcl ]; then
  terraform -chdir=infra/terraform/bootstrap init -input=false
  terraform -chdir=infra/terraform/bootstrap apply -input=false -auto-approve
fi
tf init -input=false -backend-config=backend.hcl

echo "== registries and the secret container"
# Images and secret values must exist before the services start.
tf apply -input=false -auto-approve \
  -target=aws_ecr_repository.app -target=aws_secretsmanager_secret.app
scripts/deploy/secrets.sh

echo "== images $tag (linux/arm64)"
region=$(tf output -raw region)
repos=$(tf output -json ecr_repositories)
registry=$(jq -r '.api' <<<"$repos" | cut -d/ -f1)
aws ecr get-login-password --region "$region" |
  docker login --username AWS --password-stdin "$registry" >/dev/null

build() { # service dockerfile context
  local repo
  repo=$(jq -r --arg s "$1" '.[$s]' <<<"$repos")
  if aws ecr describe-images --region "$region" --repository-name "${repo#*/}" \
    --image-ids imageTag="$tag" >/dev/null 2>&1; then
    echo "$1:$tag is already in ECR"
    return
  fi
  docker buildx build --platform linux/arm64 -f "$2" -t "$repo:$tag" --push "$3"
}
build api services/api/Dockerfile .
build worker services/worker/Dockerfile .
build core-mock services/core_mock/Dockerfile .
build mcp services/mcp_server/Dockerfile .
build ui ui/Dockerfile ui

echo "== infrastructure"
tf apply -input=false -auto-approve -var "image_tag=$tag"

echo "== migrations"
cluster=$(tf output -raw cluster)
migrate=$(tf output -json migrate)
subnets=$(jq -r '.subnets | join(",")' <<<"$migrate")
sg=$(jq -r '.security_group' <<<"$migrate")
task=$(aws ecs run-task --region "$region" --cluster "$cluster" --launch-type FARGATE \
  --task-definition "$(jq -r '.task_definition' <<<"$migrate")" \
  --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$sg],assignPublicIp=DISABLED}" \
  --query 'tasks[0].taskArn' --output text)
aws ecs wait tasks-stopped --region "$region" --cluster "$cluster" --tasks "$task"
code=$(aws ecs describe-tasks --region "$region" --cluster "$cluster" --tasks "$task" \
  --query 'tasks[0].containers[0].exitCode' --output text)
[ "$code" = "0" ] || { echo "migration failed (exit $code); see the migrate log group" >&2; exit 1; }

echo "== services"
# The api and the worker may have started before the schema existed.
for svc in api worker; do
  aws ecs update-service --region "$region" --cluster "$cluster" --service "$svc" \
    --force-new-deployment >/dev/null
done
services=()  # no mapfile: macOS ships bash 3.2
while IFS= read -r svc; do services+=("$svc"); done < <(tf output -json services | jq -r '.[]')
aws ecs wait services-stable --region "$region" --cluster "$cluster" --services "${services[@]}"

echo
echo "ClaimPilot runs at $(tf output -raw url)"
echo "Demo password: aws secretsmanager get-secret-value --region $region \\"
echo "  --secret-id $(tf output -raw app_secret_arn) --query SecretString --output text | jq -r .DEMO_PASSWORD"
