# Six Fargate services on ARM64 (Graviton, about 20 % below x86 in Frankfurt):
#   ui        Next.js review app, behind the load balancer
#   api       FastAPI, behind the load balancer under /api/*, reachable inside as http://api:8000
#   worker    every pipeline step and every model call (Claude on Bedrock, masked images only)
#   core-mock the target core claims system, inside only
#   erp-mock  the mock ERP (master data, UBL intake; bearer token), inside only, core-mock's image
#   mcp       read-only MCP tools over the api, inside only
# Service Connect gives them short names; nothing but the load balancer is reachable from outside.

resource "aws_ecs_cluster" "main" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enhanced"
  }
}

resource "aws_service_discovery_http_namespace" "main" {
  name = local.name
}

resource "aws_cloudwatch_log_group" "service" {
  #checkov:skip=CKV_AWS_338:Logs hold claim ids and step names, no personal data; 30 days serve debugging (var.log_retention_days).
  for_each          = toset(["ui", "api", "worker", "core-mock", "erp-mock", "mcp", "migrate"])
  name              = "/claimpilot/${var.environment}/${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

locals {
  # The api and the worker send spans to an ADOT sidecar on localhost, which forwards them to
  # X-Ray (infra/adot/collector.yaml). The sidecar is not essential: tracing never stops a task.
  traced = ["api", "worker"]
  trace_env = {
    for s in local.traced : s => {
      CLAIMPILOT_OTEL_ENDPOINT = "http://127.0.0.1:4318"
      OTEL_SERVICE_NAME        = "claimpilot-${s}"
    }
  }
  adot_container = {
    for s in local.traced : s => {
      name                   = "adot"
      image                  = "${local.account_id}.dkr.ecr.${var.region}.amazonaws.com/${aws_ecr_pull_through_cache_rule.ecr_public.ecr_repository_prefix}/aws-observability/aws-otel-collector:${var.adot_image_tag}"
      essential              = false
      readonlyRootFilesystem = true
      environment            = [{ name = "AOT_CONFIG_CONTENT", value = file("${path.module}/../adot/collector.yaml") }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.service[s].name
          awslogs-region        = var.region
          awslogs-stream-prefix = "adot"
        }
      }
    }
  }

  database_url = "postgresql+psycopg://claimpilot@${aws_db_instance.main.address}:5432/claimpilot?sslmode=require"

  common_env = {
    CLAIMPILOT_DATABASE_URL  = local.database_url
    CLAIMPILOT_STORAGE_DIR   = "/data/storage"
    CLAIMPILOT_CORE_MOCK_URL = "http://core-mock:8000"
    CLAIMPILOT_LANGFUSE_HOST = ""
    CLAIMPILOT_ENVIRONMENT   = "production" # api and worker refuse to start with dev leftovers
    AWS_REGION               = var.region
  }

  services = {
    ui = {
      cpu     = 512, memory = 1024, count = var.ha ? 2 : 1, port = 3000, efs = false
      env     = { CLAIMPILOT_API_URL = "http://api:8000", HOSTNAME = "0.0.0.0", PORT = "3000" }
      secrets = []
      # Next.js writes its fetch and image caches here.
      scratch = ["/tmp", "/app/.next/cache"]
    }
    api = {
      cpu     = 1024, memory = 2048, count = var.ha ? 2 : 1, port = 8000, efs = true
      env     = local.common_env
      secrets = ["database_password", "redis_url", "pii_vault_key", "session_secret", "intake_token", "mcp_token"]
      scratch = ["/tmp"]
    }
    worker = {
      cpu = var.worker.cpu, memory = var.worker.memory, count = var.worker.count, port = null, efs = true
      env = merge(local.common_env, {
        CLAIMPILOT_PROVIDERS_FILE = "providers.cloud.yaml"
        CLAIMPILOT_AWS_REGION     = var.region
        CLAIMPILOT_OCR_ENGINE     = var.ocr_engine
        CLAIMPILOT_ERP_URL        = "http://erp-mock:8000"
        # Models are baked into the image; nothing may be fetched at run time (no internet route).
        HF_HUB_OFFLINE       = "1"
        TRANSFORMERS_OFFLINE = "1"
      })
      secrets = ["database_password", "redis_url", "pii_vault_key", "erp_token"]
      scratch = ["/tmp"]
    }
    core-mock = {
      cpu = 256, memory = 512, count = 1, port = 8000, efs = false
      env = {}, secrets = [], scratch = ["/tmp"]
    }
    erp-mock = {
      cpu = 256, memory = 512, count = 1, port = 8000, efs = false
      # The core-mock image holds the ERP's records (data/invoices); only the command differs.
      image   = "core-mock"
      command = ["uvicorn", "claimpilot_core_mock.erp:app", "--host", "0.0.0.0", "--port", "8000"]
      env     = {}, secrets = ["erp_mock_token"], scratch = ["/tmp"]
    }
    mcp = {
      cpu     = 256, memory = 512, count = 1, port = 8000, efs = false
      env     = { CLAIMPILOT_API_URL = "http://api:8000" }
      secrets = ["mcp_token"]
      scratch = ["/tmp"]
    }
  }
}

resource "aws_ecs_task_definition" "service" {
  for_each                 = local.services
  family                   = "${local.name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = each.value.cpu
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = contains(["api", "worker"], each.key) ? aws_iam_role.task[each.key].arn : null

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode(concat([merge({
    name                   = each.key
    image                  = "${aws_ecr_repository.app[try(each.value.image, each.key)].repository_url}:${var.image_tag}"
    essential              = true
    readonlyRootFilesystem = true
    portMappings = each.value.port == null ? [] : [{
      name          = each.key
      containerPort = each.value.port
      protocol      = "tcp"
    }]
    environment = [
      for k, v in merge(each.value.env, contains(local.traced, each.key) ? local.trace_env[each.key] : {}) :
      { name = k, value = v }
    ]
    secrets = [for s in each.value.secrets : merge(local.secret_env, local.erp_secret_env)[s]]
    mountPoints = concat(
      [for i, p in each.value.scratch : { sourceVolume = "scratch-${i}", containerPath = p, readOnly = false }],
      each.value.efs ? [{ sourceVolume = "documents", containerPath = "/data/storage", readOnly = false }] : [],
    )
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.service[each.key].name
        awslogs-region        = var.region
        awslogs-stream-prefix = each.key
      }
    }
  }, try(each.value.command, null) == null ? {} : { command = each.value.command })], contains(local.traced, each.key) ? [local.adot_container[each.key]] : []))

  dynamic "volume" {
    for_each = { for i, p in each.value.scratch : "scratch-${i}" => p }
    content {
      name = volume.key
    }
  }

  dynamic "volume" {
    for_each = each.value.efs ? ["documents"] : []
    content {
      name = "documents"
      efs_volume_configuration {
        file_system_id     = aws_efs_file_system.documents.id
        transit_encryption = "ENABLED"
        authorization_config {
          access_point_id = aws_efs_access_point.documents.id
          iam             = "ENABLED"
        }
      }
    }
  }
}

resource "aws_ecs_service" "service" {
  for_each               = local.services
  name                   = each.key
  cluster                = aws_ecs_cluster.main.id
  task_definition        = aws_ecs_task_definition.service[each.key].arn
  desired_count          = each.value.count
  launch_type            = "FARGATE"
  enable_execute_command = false
  propagate_tags         = "SERVICE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.apps.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.main.arn

    dynamic "service" {
      for_each = each.value.port == null || each.key == "ui" ? [] : [each.key]
      content {
        port_name      = each.key
        discovery_name = each.key
        client_alias {
          port     = each.value.port
          dns_name = each.key
        }
      }
    }
  }

  dynamic "load_balancer" {
    for_each = contains(["ui", "api"], each.key) ? [each.key] : []
    content {
      target_group_arn = aws_lb_target_group.app[each.key].arn
      container_name   = each.key
      container_port   = each.value.port
    }
  }

  depends_on = [aws_lb_listener.http, aws_efs_mount_target.documents]
}

# One-off task the deploy runs before the services roll: `alembic upgrade head` with the api image.
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${local.name}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name                   = "migrate"
    image                  = "${aws_ecr_repository.app["api"].repository_url}:${var.image_tag}"
    essential              = true
    readonlyRootFilesystem = true
    command                = ["alembic", "upgrade", "head"]
    environment            = [{ name = "CLAIMPILOT_DATABASE_URL", value = local.database_url }]
    secrets                = [local.secret_env["database_password"]]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.service["migrate"].name
        awslogs-region        = var.region
        awslogs-stream-prefix = "migrate"
      }
    }
  }])
}
