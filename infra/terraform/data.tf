# Postgres with pgvector, Valkey for the job queue, EFS for uploaded documents and page renders.

resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "main" {
  name   = local.name
  family = "postgres17"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }
}

resource "aws_db_instance" "main" {
  #checkov:skip=CKV_AWS_157:Multi-AZ follows var.ha; off for the demo to halve the database cost.
  #checkov:skip=CKV_AWS_161:The app connects with a password from Secrets Manager; IAM tokens expire every 15 minutes and SQLAlchemy's pool would need a token hook. Listed in docs/deploy.md as a hardening step.
  #checkov:skip=CKV2_AWS_30:Query logging stays off: SQL parameters would carry claim content into CloudWatch.
  identifier     = local.name
  engine         = "postgres"
  engine_version = "17"
  # pgvector 0.8.2 ships with current PostgreSQL 17 minors (docs/research/aws-bedrock-facts.md);
  # the first migration runs CREATE EXTENSION vector.
  instance_class        = var.db_instance_class
  allocated_storage     = 20
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.main.arn

  db_name  = "claimpilot"
  username = "claimpilot"
  # RDS keeps the password in Secrets Manager, encrypted with the project key; it never appears
  # in Terraform state. Tasks receive it through the secret's "password" key.
  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.main.arn

  db_subnet_group_name   = aws_db_subnet_group.main.name
  parameter_group_name   = aws_db_parameter_group.main.name
  vpc_security_group_ids = [aws_security_group.data.id]
  publicly_accessible    = false
  multi_az               = var.ha

  backup_retention_period         = 7
  copy_tags_to_snapshot           = true
  deletion_protection             = var.deletion_protection
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${local.name}-final"
  auto_minor_version_upgrade      = true
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  performance_insights_enabled          = true
  performance_insights_kms_key_id       = aws_kms_key.main.arn
  performance_insights_retention_period = 7
  monitoring_interval                   = 60
  monitoring_role_arn                   = aws_iam_role.rds_monitoring.arn
}

resource "aws_elasticache_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "main" {
  #checkov:skip=CKV2_AWS_50:Failover follows var.ha; a lost queue node loses queued job ids only, and the worker re-enqueues claims that stopped moving (pipeline.py).
  replication_group_id = local.name
  description          = "arq job queue"
  engine               = "valkey"
  engine_version       = "8.0"
  node_type            = var.cache_node_type
  num_cache_clusters   = var.ha ? 2 : 1
  port                 = 6379

  automatic_failover_enabled = var.ha
  multi_az_enabled           = var.ha

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.data.id]

  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.main.arn
  transit_encryption_enabled = true
  # The token is in Terraform state (ElastiCache has no managed-secret option); state is encrypted
  # with its own key in the bootstrap bucket. The queue holds job ids, never claim content.
  auth_token                 = random_password.redis.result
  auth_token_update_strategy = "ROTATE"

  snapshot_retention_limit = 1
}

resource "aws_efs_file_system" "documents" {
  creation_token   = "${local.name}-documents"
  encrypted        = true
  kms_key_id       = aws_kms_key.main.arn
  performance_mode = "generalPurpose"
  throughput_mode  = "elastic"

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = { Name = "${local.name}-documents" }
}

resource "aws_efs_backup_policy" "documents" {
  file_system_id = aws_efs_file_system.documents.id

  backup_policy {
    status = "ENABLED"
  }
}

resource "aws_efs_mount_target" "documents" {
  count           = 2
  file_system_id  = aws_efs_file_system.documents.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.data.id]
}

# The api and the worker mount the same directory as uid 1000, whatever user the image runs as.
resource "aws_efs_access_point" "documents" {
  file_system_id = aws_efs_file_system.documents.id

  posix_user {
    uid = 1000
    gid = 1000
  }

  root_directory {
    path = "/storage"
    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0750"
    }
  }
}

resource "aws_efs_file_system_policy" "documents" {
  file_system_id = aws_efs_file_system.documents.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "TlsOnly"
        Effect    = "Deny"
        Principal = { AWS = "*" }
        Action    = "*"
        Resource  = aws_efs_file_system.documents.arn
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "TasksThroughTheAccessPoint"
        Effect    = "Allow"
        Principal = { AWS = [aws_iam_role.task["api"].arn, aws_iam_role.task["worker"].arn] }
        Action    = ["elasticfilesystem:ClientMount", "elasticfilesystem:ClientWrite"]
        Resource  = aws_efs_file_system.documents.arn
        Condition = {
          StringEquals = { "elasticfilesystem:AccessPointArn" = aws_efs_access_point.documents.arn }
        }
      },
    ]
  })
}

resource "random_password" "redis" {
  length  = 48
  special = false
}
