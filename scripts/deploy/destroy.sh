#!/usr/bin/env bash
# Remove the deployed stack: `make destroy`. Keeps the state bucket (bootstrap/) and leaves a
# final database snapshot named claimpilot-<environment>-final. The secrets go at once, the PII
# vault key with them (docs/deploy.md).
set -euo pipefail
cd "$(dirname "$0")/../.."

tf() { terraform -chdir=infra/terraform "$@"; }
tf init -input=false -backend-config=backend.hcl >/dev/null

read -r -p "Destroy the ClaimPilot stack in $(tf output -raw region)? Type 'destroy': " answer
[ "$answer" = "destroy" ] || { echo "aborted"; exit 1; }

# Deletion protection first, on the two resources that carry it, without touching anything else.
tf apply -input=false -auto-approve -var deletion_protection=false \
  -target=aws_db_instance.main -target=aws_lb.main
tf destroy -input=false -auto-approve -var deletion_protection=false
