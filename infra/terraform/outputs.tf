output "url" {
  description = "Where the review app answers."
  value       = "${local.https ? "https" : "http"}://${aws_lb.main.dns_name}"
}

output "region" {
  value = var.region
}

output "cluster" {
  value = aws_ecs_cluster.main.name
}

output "services" {
  value = keys(local.services)
}

output "ecr_repositories" {
  description = "Image name per service; the deploy pushes <url>:<git sha>."
  value       = { for k, r in aws_ecr_repository.app : k => r.repository_url }
}

output "migrate" {
  description = "What `aws ecs run-task` needs for the migration task."
  value = {
    task_definition = aws_ecs_task_definition.migrate.family
    subnets         = aws_subnet.private[*].id
    security_group  = aws_security_group.apps.id
  }
}

output "app_secret_arn" {
  description = "scripts/deploy/secrets.sh writes the application secrets here."
  value       = aws_secretsmanager_secret.app.arn
}

output "app_secret_keys" {
  value = local.app_secret_keys
}
