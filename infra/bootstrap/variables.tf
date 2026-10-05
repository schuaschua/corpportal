variable "subscription_id" { type = string }

variable "primary_region" {
  type    = string
  default = "westus3"
}

variable "secondary_region" {
  type    = string
  default = "northcentralus"
}

variable "dev_region" {
  description = "The dev environment (single region, no Front Door); its own quota, so dev and prod can run at once."
  type        = string
  default     = "westus2"
}

variable "acr_name" {
  type    = string
  default = "exampleacr"
}

variable "acr_resource_group" {
  type    = string
  default = "rg-example-shared"
}

variable "tfstate_account" {
  type    = string
  default = "stexampletfstate"
}

variable "tfstate_resource_group" {
  type    = string
  default = "rg-tfstate-sea"
}

locals {
  tags = {
    application        = "corportal"
    costCentre         = "poc"
    dataClassification = "synthetic"
    environment        = "poc"
    owner              = "platform-team"
    destroyBy          = "2026-10-04"
  }

  workload_rgs = {
    "rg-corportal-primary"   = var.primary_region   # AKS region 1, Kong/Istio/Vault/Prometheus/Grafana
    "rg-corportal-secondary" = var.secondary_region # AKS region 2 (Saturday only), SQL secondary
    "rg-corportal-data"      = var.primary_region   # ADLS, Azure SQL, Event Hubs, Databricks, Key Vault, Front Door
    # dev (infra/main/environments/dev.tfvars): one region, Kong's public IP, no Front Door
    "rg-corportal-dev-primary" = var.dev_region # AKS, Kong/Istio/Vault/Prometheus
    "rg-corportal-dev-data"    = var.dev_region # ADLS, Azure SQL, Event Hubs, Databricks, Key Vault
  }

  # Built-in role definition GUIDs Jenkins may assign inside the workload RGs.
  assignable_roles = [
    "7f951dda-4ed3-4680-a7ca-43fe172d538d", # AcrPull
    "4d97b98b-1d4f-4787-a291-c67834d212e7", # Network Contributor (AKS on custom VNet)
    "f1a07417-d97a-45cb-824c-7a7467783830", # Managed Identity Operator (AKS kubelet identity)
    "b12aa53e-6015-4669-85d0-8515ebb3ae7f", # Private DNS Zone Contributor
    "ba92f5b4-2d11-453d-a403-e96b0029c9fe", # Storage Blob Data Contributor (Databricks Access Connector -> ADLS)
    "4633458b-17de-408a-b874-0445c86b69e6", # Key Vault Secrets User
    "b86a8fe4-44ce-4948-aee5-eccb2c155cd7", # Key Vault Secrets Officer
    "12338af0-0e69-4776-bea7-57ae8d297424", # Key Vault Crypto User (Vault auto-unseal)
    "14b46e9e-c2b7-41b4-b07b-48a6ebf60603", # Key Vault Crypto Officer (Jenkins creates the unseal key)
    "2b629674-e913-4c01-ae53-ef4638d8f975", # Azure Event Hubs Data Sender
    "a638d3c7-ab3a-418d-83e6-5f17a39d4fde", # Azure Event Hubs Data Receiver
  ]

  roles_csv = join(", ", local.assignable_roles)

  rbac_condition = <<-EOT
    (
      (!(ActionMatches{'Microsoft.Authorization/roleAssignments/write'}))
      OR
      (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${local.roles_csv}})
    )
    AND
    (
      (!(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'}))
      OR
      (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${local.roles_csv}})
    )
  EOT

  acr_pull_only_condition = <<-EOT
    (
      (!(ActionMatches{'Microsoft.Authorization/roleAssignments/write'}))
      OR
      (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {7f951dda-4ed3-4680-a7ca-43fe172d538d})
    )
    AND
    (
      (!(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'}))
      OR
      (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {7f951dda-4ed3-4680-a7ca-43fe172d538d})
    )
  EOT
}
