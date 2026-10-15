# Two AZs. Public subnets hold only the load balancer. Tasks, the database, the cache and the
# file system sit in private subnets with no route to the internet: no NAT gateway, no internet
# egress. AWS APIs (Bedrock, ECR, Logs, Secrets Manager) are reached through VPC endpoints, so a
# claim's content can only leave the VPC towards the services this file lists.

data "aws_caller_identity" "current" {}

locals {
  name       = "claimpilot-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id
  azs        = var.azs
  # Interface endpoints cost per AZ and hour; one AZ is enough for the demo.
  endpoint_subnets = var.ha ? aws_subnet.private[*].id : [aws_subnet.private[0].id]
  interface_endpoints = toset([
    "bedrock-runtime",
    "ecr.api",
    "ecr.dkr",
    "logs",
    "secretsmanager",
  ])
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

# The default security group of the VPC allows nothing.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id
}

resource "aws_flow_log" "vpc" {
  vpc_id               = aws_vpc.main.id
  traffic_type         = "REJECT"
  log_destination_type = "cloud-watch-logs"
  log_destination      = aws_cloudwatch_log_group.flow.arn
  iam_role_arn         = aws_iam_role.flow_logs.arn
}

resource "aws_cloudwatch_log_group" "flow" {
  #checkov:skip=CKV_AWS_338:Rejected-traffic logs for debugging, kept as long as app logs (var.log_retention_days).
  name              = "/claimpilot/${var.environment}/vpc-flow"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_subnet" "public" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index)
  tags              = { Name = "${local.name}-public-${count.index}" }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  availability_zone = local.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 10 + count.index)
  tags              = { Name = "${local.name}-private-${count.index}" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# No default route: private subnets reach only the VPC and the endpoints below.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ECR stores image layers in S3; the gateway endpoint is free.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = local.interface_endpoints
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.endpoint_subnets
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
}

# --- Security groups -------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Load balancer: HTTP(S) from allowed_cidrs, out to the ui and api tasks"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  for_each          = toset(var.allowed_cidrs)
  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from an allowed network"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  for_each          = toset(var.allowed_cidrs)
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from an allowed network (redirects to HTTPS when a certificate is set)"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_egress_rule" "alb_to_apps" {
  for_each                     = { ui = 3000, api = 8000 }
  security_group_id            = aws_security_group.alb.id
  description                  = "To the ${each.key} tasks"
  referenced_security_group_id = aws_security_group.apps.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}

# All ECS tasks share one group: they talk to each other over Service Connect on 8000 and
# leave the group only towards the data stores and the endpoints.
resource "aws_security_group" "apps" {
  name        = "${local.name}-apps"
  description = "ECS tasks"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "apps_from_alb" {
  for_each                     = { ui = 3000, api = 8000 }
  security_group_id            = aws_security_group.apps.id
  description                  = "${each.key} from the load balancer"
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}

resource "aws_vpc_security_group_ingress_rule" "apps_internal" {
  security_group_id            = aws_security_group.apps.id
  description                  = "Service Connect between tasks (api, core-mock, mcp)"
  referenced_security_group_id = aws_security_group.apps.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_vpc_security_group_egress_rule" "apps" {
  for_each = {
    internal  = { sg = aws_security_group.apps.id, from = 8000, to = 8000 }
    postgres  = { sg = aws_security_group.data.id, from = 5432, to = 5432 }
    redis     = { sg = aws_security_group.data.id, from = 6379, to = 6379 }
    efs       = { sg = aws_security_group.data.id, from = 2049, to = 2049 }
    endpoints = { sg = aws_security_group.endpoints.id, from = 443, to = 443 }
  }
  security_group_id            = aws_security_group.apps.id
  description                  = "To ${each.key}"
  referenced_security_group_id = each.value.sg
  ip_protocol                  = "tcp"
  from_port                    = each.value.from
  to_port                      = each.value.to
}

resource "aws_vpc_security_group_egress_rule" "apps_s3" {
  security_group_id = aws_security_group.apps.id
  description       = "To S3 through the gateway endpoint (ECR image layers)"
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_security_group" "data" {
  name        = "${local.name}-data"
  description = "Postgres, Valkey and EFS: reachable from the ECS tasks only"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "data" {
  for_each                     = { postgres = 5432, redis = 6379, efs = 2049 }
  security_group_id            = aws_security_group.data.id
  description                  = "${each.key} from the ECS tasks"
  referenced_security_group_id = aws_security_group.apps.id
  ip_protocol                  = "tcp"
  from_port                    = each.value
  to_port                      = each.value
}

resource "aws_security_group" "endpoints" {
  name        = "${local.name}-endpoints"
  description = "VPC interface endpoints: HTTPS from the ECS tasks"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "endpoints" {
  security_group_id            = aws_security_group.endpoints.id
  description                  = "HTTPS from the ECS tasks"
  referenced_security_group_id = aws_security_group.apps.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
