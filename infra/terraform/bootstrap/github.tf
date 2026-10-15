# GitHub Actions without stored AWS keys: an OIDC provider and two roles that only this
# repository's workflows can assume.
#   deploy  .github/workflows/deploy.yml, only from the "production" environment (add a reviewer)
#   eval    .github/workflows/eval-live.yml on pull requests: Bedrock invoke and nothing else
# Skipped while github_repository is null.

variable "github_repository" {
  description = "owner/repo whose workflows may assume the roles; null creates none."
  type        = string
  default     = null
}

variable "claude_models" {
  type    = list(string)
  default = ["anthropic.claude-haiku-5-5", "anthropic.claude-sonnet-5-5", "anthropic.claude-opus-5-5"]
}

variable "eu_inference_regions" {
  type    = list(string)
  default = ["eu-central-1", "eu-north-1", "eu-south-1", "eu-south-2", "eu-west-1", "eu-west-3"]
}

locals {
  github     = var.github_repository != null
  account_id = data.aws_caller_identity.current.account_id
  oidc       = "token.actions.githubusercontent.com"
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = local.github ? 1 : 0
  url            = "https://${local.oidc}"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "trust" {
  for_each = local.github ? {
    deploy = "repo:${var.github_repository}:environment:production"
    eval   = "repo:${var.github_repository}:pull_request"
  } : {}

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github[0].arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc}:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.oidc}:sub"
      values   = [each.value]
    }
  }
}

resource "aws_iam_role" "github" {
  for_each             = data.aws_iam_policy_document.trust
  name                 = "claimpilot-github-${each.key}"
  assume_role_policy   = each.value.json
  max_session_duration = 7200
}

# Deploy: everything Terraform manages here except IAM, plus IAM limited to this project's roles.
resource "aws_iam_role_policy_attachment" "deploy_power_user" {
  count      = local.github ? 1 : 0
  role       = aws_iam_role.github["deploy"].name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

resource "aws_iam_role_policy" "deploy_iam" {
  #checkov:skip=CKV_AWS_286:Terraform creates and attaches the stack's roles; the resources are limited to the claimpilot- prefix.
  #checkov:skip=CKV_AWS_287:Same: role management is the deploy's job, scoped to claimpilot- roles.
  #checkov:skip=CKV_AWS_288:Same: scoped to claimpilot- roles and policies.
  #checkov:skip=CKV_AWS_289:Same: scoped to claimpilot- roles and policies.
  #checkov:skip=CKV_AWS_290:Same: scoped to claimpilot- roles and policies.
  #checkov:skip=CKV_AWS_355:iam:CreateServiceLinkedRole and the List calls take no resource scope.
  count = local.github ? 1 : 0
  name  = "project-iam"
  role  = aws_iam_role.github["deploy"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ProjectRoles"
        Effect = "Allow"
        Action = [
          "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:UpdateRole", "iam:TagRole",
          "iam:UntagRole", "iam:UpdateAssumeRolePolicy", "iam:PassRole",
          "iam:PutRolePolicy", "iam:GetRolePolicy", "iam:DeleteRolePolicy", "iam:ListRolePolicies",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
        ]
        Resource = "arn:aws:iam::${local.account_id}:role/claimpilot-*"
      },
      {
        Sid      = "ServiceLinkedRolesAndReads"
        Effect   = "Allow"
        Action   = ["iam:CreateServiceLinkedRole", "iam:ListRoles", "iam:ListPolicies", "iam:GetPolicy", "iam:GetPolicyVersion"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy" "eval_bedrock" {
  count = local.github ? 1 : 0
  name  = "bedrock-invoke"
  role  = aws_iam_role.github["eval"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
      Resource = concat(
        [for m in var.claude_models : "arn:aws:bedrock:${var.region}:${local.account_id}:inference-profile/eu.${m}"],
        flatten([for r in var.eu_inference_regions : [for m in var.claude_models : "arn:aws:bedrock:${r}::foundation-model/${m}"]]),
        ["arn:aws:bedrock:${var.region}::foundation-model/cohere.embed-multilingual-v3"],
      )
    }]
  })
}

output "deploy_role_arn" {
  value = local.github ? aws_iam_role.github["deploy"].arn : null
}

output "eval_role_arn" {
  value = local.github ? aws_iam_role.github["eval"].arn : null
}

output "state_kms_key" {
  description = "TF_STATE_KMS_KEY for the deploy workflow."
  value       = aws_kms_key.state.arn
}
