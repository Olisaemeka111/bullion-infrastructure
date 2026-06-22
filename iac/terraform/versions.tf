terraform {
  required_version = ">= 1.10.0" # S3 native state locking (use_lockfile)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    google = {
      source  = "hashicorp/google"
      version = "~> 5.20"
    }
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.95"
    }
  }
}
