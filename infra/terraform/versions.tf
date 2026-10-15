terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State lives in the bucket that bootstrap/ creates (S3 native locking, no DynamoDB table).
  # `terraform init -backend-config=backend.hcl`; see backend.hcl.example.
  backend "s3" {}
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "claimpilot"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
