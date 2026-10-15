# One customer-managed key for everything that holds claim data or secrets: RDS, EFS, Secrets
# Manager, ECR, CloudWatch Logs. Rotated yearly.

resource "aws_kms_key" "main" {
  description             = "${local.name}: claims data, secrets, logs"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = jsonencode(local.kms_policy)
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.main.key_id
}

locals {
  kms_policy = {
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountAdministers"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${var.region}.amazonaws.com" }
        Action    = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
        Resource  = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = [
              "arn:aws:logs:${var.region}:${local.account_id}:log-group:/claimpilot/${var.environment}/*",
              "arn:aws:logs:${var.region}:${local.account_id}:log-group:aws-waf-logs-${local.name}",
            ]
          }
        }
      },
    ]
  }
}
