#!/usr/bin/env bash
# Write the application secrets once. The values are generated here and piped straight into
# Secrets Manager: they never enter Terraform state, shell history or process arguments.
# Run by deploy.sh; safe to run again (an existing value is left alone).
set -euo pipefail
cd "$(dirname "$0")/../.."

tf() { terraform -chdir=infra/terraform "$@"; }
arn=$(tf output -raw app_secret_arn)
region=$(tf output -raw region)

if aws secretsmanager get-secret-value --secret-id "$arn" --region "$region" >/dev/null 2>&1; then
  echo "app secret already has a value; left as it is"
  exit 0
fi

uv run --no-sync python - <<'PY' | aws secretsmanager put-secret-value \
  --secret-id "$arn" --region "$region" --secret-string file:///dev/stdin >/dev/null
import json
import secrets

from cryptography.fernet import Fernet

print(json.dumps({
    "PII_VAULT_KEY": Fernet.generate_key().decode(),
    "SESSION_SECRET": secrets.token_urlsafe(48),
    "DEMO_PASSWORD": secrets.token_urlsafe(18),
    "INTAKE_TOKEN": secrets.token_urlsafe(32),
    "MCP_TOKEN": secrets.token_urlsafe(32),
}), end="")
PY

echo "app secret written to $arn"
