# Application secrets. Terraform creates the containers, not the values: scripts/deploy/secrets.sh
# generates the values once and writes them with the AWS CLI, so the PII vault key never sits in
# Terraform state. The database password is RDS-managed (data.tf).

resource "aws_secretsmanager_secret" "app" {
  #checkov:skip=CKV2_AWS_57:Rotating the PII vault key means re-encrypting the vault; that is a migration, not a Lambda rotation. docs/deploy.md describes it.
  name        = "${local.name}/app"
  description = "JSON: PII_VAULT_KEY, SESSION_SECRET, DEMO_PASSWORD, INTAKE_TOKEN, MCP_TOKEN"
  kms_key_id  = aws_kms_key.main.arn
  # Demo stack: destroy deletes the secret at once, so a redeploy can reuse the name. A production
  # stack needs a recovery window: the vault key is the only way to read pii.vault.
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "redis_url" {
  #checkov:skip=CKV2_AWS_57:The token rotates with the cache's auth_token_update_strategy on the next apply, not by a Lambda.
  name                    = "${local.name}/redis-url"
  description             = "rediss:// URL with the Valkey auth token"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "redis_url" {
  secret_id     = aws_secretsmanager_secret.redis_url.id
  secret_string = "rediss://:${random_password.redis.result}@${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
}

locals {
  app_secret_keys = ["PII_VAULT_KEY", "SESSION_SECRET", "DEMO_PASSWORD", "INTAKE_TOKEN", "MCP_TOKEN"]

  # ECS "secrets" entries, per service. valueFrom "<arn>:<json key>::" picks one key of a JSON secret.
  secret_env = {
    database_password = { name = "CLAIMPILOT_DATABASE_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" }
    redis_url         = { name = "CLAIMPILOT_REDIS_URL", valueFrom = aws_secretsmanager_secret.redis_url.arn }
    pii_vault_key     = { name = "CLAIMPILOT_PII_VAULT_KEY", valueFrom = "${aws_secretsmanager_secret.app.arn}:PII_VAULT_KEY::" }
    session_secret    = { name = "CLAIMPILOT_SESSION_SECRET", valueFrom = "${aws_secretsmanager_secret.app.arn}:SESSION_SECRET::" }
    demo_password     = { name = "CLAIMPILOT_DEMO_PASSWORD", valueFrom = "${aws_secretsmanager_secret.app.arn}:DEMO_PASSWORD::" }
    intake_token      = { name = "CLAIMPILOT_INTAKE_TOKEN", valueFrom = "${aws_secretsmanager_secret.app.arn}:INTAKE_TOKEN::" }
    mcp_token         = { name = "CLAIMPILOT_MCP_TOKEN", valueFrom = "${aws_secretsmanager_secret.app.arn}:MCP_TOKEN::" }
  }
}
