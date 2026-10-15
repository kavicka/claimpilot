# One execution role (pull images, write logs, read the secrets the task definitions name) and a
# task role only for the services that call AWS: the worker (Bedrock) and the api (EFS through
# the file system policy). The ui, core-mock and mcp tasks run without a task role.

locals {
  ecs_assume = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        ArnLike      = { "aws:SourceArn" = "arn:aws:ecs:${var.region}:${local.account_id}:*" }
        StringEquals = { "aws:SourceAccount" = local.account_id }
      }
    }]
  })

  claude_profiles = [
    for m in var.claude_models : "arn:aws:bedrock:${var.region}:${local.account_id}:inference-profile/eu.${m}"
  ]
  claude_models = flatten([
    for r in var.eu_inference_regions : [for m in var.claude_models : "arn:aws:bedrock:${r}::foundation-model/${m}"]
  ])
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = local.ecs_assume
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "secrets"
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "secretsmanager:GetSecretValue"
        Resource = [
          aws_secretsmanager_secret.app.arn,
          aws_secretsmanager_secret.redis_url.arn,
          aws_db_instance.main.master_user_secret[0].secret_arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = aws_kms_key.main.arn
      },
    ]
  })
}

resource "aws_iam_role" "task" {
  for_each           = toset(["api", "worker"])
  name               = "${local.name}-${each.key}"
  assume_role_policy = local.ecs_assume
}

resource "aws_iam_role_policy" "worker_bedrock" {
  name = "bedrock"
  role = aws_iam_role.task["worker"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ClaudeThroughTheEuProfiles"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = concat(local.claude_profiles, local.claude_models)
      },
      {
        Sid      = "EmbeddingsInRegion"
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = "arn:aws:bedrock:${var.region}::foundation-model/${var.embedding_model}"
      },
    ]
  })
}

resource "aws_iam_role" "flow_logs" {
  name = "${local.name}-flow-logs"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "flow_logs" {
  name = "logs"
  role = aws_iam_role.flow_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
      Resource = "${aws_cloudwatch_log_group.flow.arn}:*"
    }]
  })
}

resource "aws_iam_role" "rds_monitoring" {
  name = "${local.name}-rds-monitoring"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}
