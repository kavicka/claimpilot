# Plan-and-apply against mocked providers: no AWS account, no credentials, no API calls.
# `terraform -chdir=infra/terraform test`

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }

  mock_resource "aws_db_instance" {
    defaults = {
      address = "claimpilot-demo.abc.eu-central-1.rds.amazonaws.com"
      master_user_secret = [{
        secret_arn    = "arn:aws:secretsmanager:eu-central-1:123456789012:secret:rds!db-1"
        kms_key_id    = "arn:aws:kms:eu-central-1:123456789012:key/1"
        secret_status = "active"
      }]
    }
  }

  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }

  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:eu-central-1:123456789012:key/1" }
  }

  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:eu-central-1:123456789012:log-group:mock" }
  }

  mock_resource "aws_lb" {
    defaults = { arn = "arn:aws:elasticloadbalancing:eu-central-1:123456789012:loadbalancer/app/claimpilot-demo/1" }
  }

  mock_resource "aws_lb_target_group" {
    defaults = { arn = "arn:aws:elasticloadbalancing:eu-central-1:123456789012:targetgroup/claimpilot-demo/1" }
  }

  mock_resource "aws_lb_listener" {
    defaults = { arn = "arn:aws:elasticloadbalancing:eu-central-1:123456789012:listener/app/claimpilot-demo/1/1" }
  }

  mock_resource "aws_wafv2_web_acl" {
    defaults = { arn = "arn:aws:wafv2:eu-central-1:123456789012:regional/webacl/claimpilot-demo/1" }
  }

  mock_resource "aws_ecr_repository" {
    defaults = { repository_url = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/claimpilot" }
  }
}

mock_provider "random" {
  mock_resource "random_password" {
    defaults = { result = "MockRedisToken0123456789abcdefMockRedisToken0123" }
  }
}

variables {
  allowed_cidrs = ["203.0.113.10/32"]
  alert_email   = "ops@example.com"
}

run "nothing_private_has_a_way_out" {
  assert {
    condition     = length(aws_route_table.private.route) == 0
    error_message = "Private subnets must have no route out of the VPC (no NAT, no internet gateway)."
  }

  assert {
    condition     = alltrue([for s in aws_ecs_service.service : s.network_configuration[0].assign_public_ip == false])
    error_message = "No task gets a public IP."
  }

  assert {
    condition     = keys(aws_vpc_security_group_ingress_rule.alb_https) == ["203.0.113.10/32"]
    error_message = "The load balancer admits allowed_cidrs only."
  }

  assert {
    condition     = aws_db_instance.main.publicly_accessible == false
    error_message = "The database is private."
  }
}

run "data_is_encrypted_at_rest_and_in_transit" {
  assert {
    condition     = aws_db_instance.main.storage_encrypted && aws_db_instance.main.manage_master_user_password
    error_message = "RDS: encrypted storage, password managed by RDS (never in state)."
  }

  assert {
    condition     = one([for p in aws_db_parameter_group.main.parameter : p.value if p.name == "rds.force_ssl"]) == "1"
    error_message = "RDS refuses connections without TLS."
  }

  assert {
    condition     = aws_elasticache_replication_group.main.at_rest_encryption_enabled == "true" && aws_elasticache_replication_group.main.transit_encryption_enabled
    error_message = "Valkey: encrypted at rest and in transit."
  }

  assert {
    condition     = aws_efs_file_system.documents.encrypted
    error_message = "EFS holds the uploaded documents; it must be encrypted."
  }

  assert {
    condition = alltrue([
      for k, td in aws_ecs_task_definition.service : alltrue([
        for v in td.volume : v.efs_volume_configuration[0].transit_encryption == "ENABLED" if length(v.efs_volume_configuration) > 0
      ])
    ])
    error_message = "EFS is mounted with TLS."
  }

  assert {
    condition     = length(aws_secretsmanager_secret_version.redis_url.secret_string) > 0 && startswith(aws_secretsmanager_secret_version.redis_url.secret_string, "rediss://")
    error_message = "The queue URL uses TLS."
  }
}

run "only_the_worker_calls_bedrock_and_only_in_the_eu" {
  assert {
    condition = alltrue([
      for s in flatten([for st in jsondecode(aws_iam_role_policy.worker_bedrock.policy).Statement : st.Resource]) :
      contains(var.eu_inference_regions, split(":", s)[3])
    ])
    error_message = "Every Bedrock resource the worker may call is in an EU Region."
  }

  assert {
    condition     = aws_iam_role_policy.worker_bedrock.role == aws_iam_role.task["worker"].id
    error_message = "The Bedrock policy belongs to the worker role."
  }

  assert {
    condition = alltrue([
      for k in ["ui", "core-mock", "mcp"] : aws_ecs_task_definition.service[k].task_role_arn == null
    ])
    error_message = "ui, core-mock and mcp run without a task role."
  }
}

run "tasks_get_what_they_need_and_no_more" {
  assert {
    condition = alltrue([
      for k, td in aws_ecs_task_definition.service : jsondecode(td.container_definitions)[0].readonlyRootFilesystem
    ])
    error_message = "Every container runs with a read-only root file system."
  }

  assert {
    condition = (
      contains([for e in jsondecode(aws_ecs_task_definition.service["worker"].container_definitions)[0].environment : "${e.name}=${e.value}"], "CLAIMPILOT_PROVIDERS_FILE=providers.cloud.yaml")
      && contains([for e in jsondecode(aws_ecs_task_definition.service["worker"].container_definitions)[0].environment : "${e.name}=${e.value}"], "HF_HUB_OFFLINE=1")
    )
    error_message = "The worker uses the cloud model map and never downloads models at run time."
  }

  assert {
    condition = (
      sort([for s in jsondecode(aws_ecs_task_definition.service["worker"].container_definitions)[0].secrets : s.name])
      == sort(["CLAIMPILOT_DATABASE_PASSWORD", "CLAIMPILOT_REDIS_URL", "CLAIMPILOT_PII_VAULT_KEY"])
    )
    error_message = "The worker sees the database, the queue and the vault key; no login or intake secrets."
  }

  assert {
    condition     = length(jsondecode(aws_ecs_task_definition.service["ui"].container_definitions)[0].secrets) == 0
    error_message = "The ui holds no secrets."
  }

  assert {
    condition     = !strcontains(aws_ecs_task_definition.service["api"].container_definitions, random_password.redis.result)
    error_message = "Secrets reach tasks through Secrets Manager, never as plain environment values."
  }
}

run "demo_size_by_default" {
  assert {
    condition     = !aws_db_instance.main.multi_az && aws_elasticache_replication_group.main.num_cache_clusters == 1
    error_message = "The demo runs single-AZ."
  }

  assert {
    condition     = length(aws_vpc_endpoint.interface["bedrock-runtime"].subnet_ids) == 1
    error_message = "One AZ of interface endpoints in the demo."
  }

  assert {
    condition     = aws_lb_listener.http.default_action[0].type == "forward" && length(aws_lb_listener.https) == 0
    error_message = "Without a certificate the listener serves HTTP."
  }
}

run "ha_and_https" {
  variables {
    ha              = true
    certificate_arn = "arn:aws:acm:eu-central-1:123456789012:certificate/abc"
  }

  assert {
    condition     = aws_db_instance.main.multi_az && aws_elasticache_replication_group.main.num_cache_clusters == 2
    error_message = "HA: Multi-AZ database and two cache nodes."
  }

  assert {
    condition     = length(aws_vpc_endpoint.interface["bedrock-runtime"].subnet_ids) == 2
    error_message = "HA: endpoints in both AZs."
  }

  assert {
    condition     = aws_lb_listener.http.default_action[0].type == "redirect" && aws_lb_listener.https[0].ssl_policy == "ELBSecurityPolicy-TLS13-1-2-2021-06"
    error_message = "With a certificate, HTTP redirects to TLS 1.2+."
  }
}

run "uploads_pass_the_waf" {
  assert {
    condition = anytrue([
      for r in aws_wafv2_web_acl.main.rule : anytrue([
        for o in r.statement[0].managed_rule_group_statement[0].rule_action_override : o.name == "SizeRestrictions_BODY" && length(o.action_to_use[0].count) == 1
      ]) if length(r.statement[0].managed_rule_group_statement) > 0
    ])
    error_message = "The managed rule's 8 KB body limit only counts; it would block every claim upload."
  }
}
