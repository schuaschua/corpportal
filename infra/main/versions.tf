terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.40"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.13"
    }
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.80"
    }
  }

  # Filled in by Jenkins with -backend-config (infra/bootstrap output `backend_config`):
  # stexampletfstate / container corportal / key main.tfstate, use_azuread_auth + use_msi.
  # Local work: terraform init -backend=false.
  backend "azurerm" {}
}
