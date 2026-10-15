# Public load balancer: /api/* to the api, everything else to the ui. Same origin for both, so
# the session cookie never crosses sites. WAF in front with AWS managed rules and a rate limit.

locals {
  https = var.certificate_arn != null
}

resource "aws_lb" "main" {
  #checkov:skip=CKV2_AWS_20:HTTP redirects to HTTPS when a certificate is set; without one the demo is HTTP-only and limited to allowed_cidrs.
  #checkov:skip=CKV_AWS_91:Access logs need a separate S3 bucket with an ELB-specific policy; WAF logs record every request already.
  #checkov:skip=CKV2_AWS_76:Log4j rules come with AWSManagedRulesKnownBadInputsRuleSet; the check also wants AnonymousIpList, which would block reviewers on VPNs while allowed_cidrs already limits who gets in.
  name                       = local.name
  load_balancer_type         = "application"
  subnets                    = aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  enable_deletion_protection = var.deletion_protection
}

resource "aws_lb_target_group" "app" {
  #checkov:skip=CKV_AWS_378:TLS ends at the load balancer; tasks sit in private subnets that only it and other tasks can reach.
  for_each    = { ui = { port = 3000, health = "/" }, api = { port = 8000, health = "/health" } }
  name        = "${local.name}-${each.key}"
  port        = each.value.port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path    = each.value.health
    matcher = "200-399"
  }
}

resource "aws_lb_listener" "https" {
  count             = local.https ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app["ui"].arn
  }
}

resource "aws_lb_listener" "http" {
  #checkov:skip=CKV_AWS_2:Plain HTTP only when no certificate is set (var.certificate_arn); otherwise this listener redirects.
  #checkov:skip=CKV_AWS_103:Same as above; the HTTPS listener uses TLS 1.2+ (ELBSecurityPolicy-TLS13-1-2-2021-06).
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = local.https ? "redirect" : "forward"
    target_group_arn = local.https ? null : aws_lb_target_group.app["ui"].arn

    dynamic "redirect" {
      for_each = local.https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = local.https ? aws_lb_listener.https[0].arn : aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app["api"].arn
  }

  condition {
    path_pattern {
      values = ["/api/*", "/health"]
    }
  }
}

resource "aws_wafv2_web_acl" "main" {
  name  = local.name
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "common"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"

        # Claim uploads are multipart bodies of several MB; the rule's 8 KB body limit would
        # block every upload. The api enforces its own size limit.
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "known-bad-inputs"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "rate-limit"
    priority = 3

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 1000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "main" {
  resource_arn = aws_lb.main.arn
  web_acl_arn  = aws_wafv2_web_acl.main.arn
}

resource "aws_cloudwatch_log_group" "waf" {
  #checkov:skip=CKV_AWS_338:Request logs, kept as long as app logs (var.log_retention_days).
  name              = "aws-waf-logs-${local.name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.main.arn
}

resource "aws_wafv2_web_acl_logging_configuration" "main" {
  resource_arn            = aws_wafv2_web_acl.main.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]

  # Session cookies and intake tokens stay out of the logs.
  redacted_fields {
    single_header {
      name = "cookie"
    }
  }

  redacted_fields {
    single_header {
      name = "authorization"
    }
  }
}
