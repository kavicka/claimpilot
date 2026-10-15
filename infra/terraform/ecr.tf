locals {
  images = toset(["api", "worker", "ui", "core-mock", "mcp"])
}

resource "aws_ecr_repository" "app" {
  for_each             = local.images
  name                 = "${local.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  # Images are rebuilt from git; destroy takes them along.
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  for_each   = aws_ecr_repository.app
  repository = each.value.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 5 images: enough to roll back, and the worker image is several GB"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}

# The ADOT collector image comes from ECR Public; tasks have no internet route, so ECR fetches it
# on the first pull and keeps a copy under ecr-public/.
resource "aws_ecr_pull_through_cache_rule" "ecr_public" {
  ecr_repository_prefix = "ecr-public"
  upstream_registry_url = "public.ecr.aws"
}
