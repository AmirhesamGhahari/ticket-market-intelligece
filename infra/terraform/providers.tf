terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }

  # Uncomment to use an S3 backend for shared/persistent state:
  # backend "s3" {
  #   bucket = "your-terraform-state-bucket"
  #   key    = "ticket-tracker/terraform.tfstate"
  #   region = "ca-central-1"
  # }
}

provider "aws" {
  region = var.region
}
