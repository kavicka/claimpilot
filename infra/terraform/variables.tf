variable "region" {
  description = "AWS Region. Claude 5.5 runs here through the EU inference profiles (ADR-010)."
  type        = string
  default     = "eu-central-1"
}

variable "environment" {
  description = "Name suffix for every resource, e.g. demo or prod."
  type        = string
  default     = "demo"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.environment))
    error_message = "Lowercase letters, digits and dashes, 2 to 16 characters."
  }
}

variable "ha" {
  description = <<-EOT
    High availability: Multi-AZ RDS, two cache nodes, VPC endpoints in both AZs, two api tasks.
    Off for the demo, where one AZ failing may take the app down for the length of the outage.
  EOT
  type        = bool
  default     = false
}

variable "azs" {
  description = "Two Availability Zones, named so the subnets never move when AWS adds a zone."
  type        = list(string)
  default     = ["eu-central-1a", "eu-central-1b"]

  validation {
    condition     = length(var.azs) == 2
    error_message = "Exactly two zones."
  }
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "allowed_cidrs" {
  description = "Who may reach the load balancer. Keep the demo closed to the people reviewing it."
  type        = list(string)

  validation {
    condition     = length(var.allowed_cidrs) > 0 && alltrue([for c in var.allowed_cidrs : can(cidrnetmask(c))])
    error_message = "At least one valid CIDR block."
  }
}

variable "certificate_arn" {
  description = "ACM certificate for HTTPS on the load balancer. Without one the demo runs on plain HTTP, reachable only from allowed_cidrs."
  type        = string
  default     = null
}

variable "image_tag" {
  description = "Image tag to run for every service (the git commit the deploy workflow built)."
  type        = string
  default     = "latest"
}

variable "budget_monthly_usd" {
  description = "Monthly cost budget; alerts at 80 % actual and 100 % forecast. The demo runs about 330 USD a month idle (docs/governance/cost.md)."
  type        = number
  default     = 400
}

variable "alert_email" {
  description = "Receives budget alerts."
  type        = string
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.small"
}

variable "cache_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

variable "worker" {
  description = "Fargate size of the worker task. Docling, OCR, NER and the reranker run on its CPU and take about 4 GB; 4 vCPU and 16 GB roughly halve parse time. count = 0 parks it between demos."
  type = object({
    cpu    = number
    memory = number
    count  = number
  })
  default = { cpu = 2048, memory = 8192, count = 1 }
}

variable "log_retention_days" {
  description = "Application logs carry claim ids and step names, no personal data; kept short."
  type        = number
  default     = 30
}

variable "claude_models" {
  description = "Model families the worker may call, through the EU inference profiles."
  type        = list(string)
  default     = ["anthropic.claude-haiku-5-5", "anthropic.claude-sonnet-5-5", "anthropic.claude-opus-5-5"]
}

variable "embedding_model" {
  type    = string
  default = "cohere.embed-multilingual-v3"
}

variable "eu_inference_regions" {
  description = "Regions the eu. profiles route to from eu-central-1 (docs/research/aws-bedrock-facts.md)."
  type        = list(string)
  default     = ["eu-central-1", "eu-north-1", "eu-south-1", "eu-south-2", "eu-west-1", "eu-west-3"]
}

variable "deletion_protection" {
  description = "Guards the database and the load balancer against destroy; scripts/deploy/destroy.sh turns it off first."
  type        = bool
  default     = true
}

variable "ocr_engine" {
  description = "OCR for scans: docling (inside the worker) or textract. Textract needs the AWS Organizations AI services opt-out policy first (docs/deploy.md)."
  type        = string
  default     = "docling"

  validation {
    condition     = contains(["docling", "textract"], var.ocr_engine)
    error_message = "docling or textract."
  }
}

variable "adot_image_tag" {
  description = "AWS Distro for OpenTelemetry collector, pulled through ECR from public.ecr.aws."
  type        = string
  default     = "v0.50.0"
}
