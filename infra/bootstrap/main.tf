# One-off bootstrap, run by a subscription Owner from a laptop. Local state.
# Creates everything Jenkins is NOT allowed to create for itself:
#   resource groups, Jenkins' own identity, its scoped roles, the tfstate container.

terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# Providers (Microsoft.Cdn, .EventHub, .Sql): the azurerm provider registers them automatically,
# so they are not managed here (they are registered in the subscription).

# ---------- resource groups
# bootstrap RG holds Jenkins' identity. Jenkins gets NO rights here, so it cannot delete or re-scope itself.
resource "azurerm_resource_group" "bootstrap" {
  name     = "rg-corportal-bootstrap"
  location = var.primary_region
  tags     = local.tags
}

resource "azurerm_resource_group" "workload" {
  for_each = local.workload_rgs
  name     = each.key
  location = each.value
  tags     = local.tags
}

# ---------- Jenkins identity
resource "azurerm_user_assigned_identity" "jenkins" {
  name                = "id-corportal-jenkins"
  resource_group_name = azurerm_resource_group.bootstrap.name
  location            = azurerm_resource_group.bootstrap.location
  tags                = local.tags
}

# Contributor on the workload RGs only
resource "azurerm_role_assignment" "contributor" {
  for_each             = azurerm_resource_group.workload
  scope                = each.value.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.jenkins.principal_id
  principal_type       = "ServicePrincipal"
}

# Constrained delegation: Jenkins may create/delete role assignments in the workload RGs,
# but ONLY for the roles the platform needs (AKS, Databricks, Vault, Event Hubs). It cannot grant Owner/Contributor/UAA.
resource "azurerm_role_assignment" "rbac_admin" {
  for_each             = azurerm_resource_group.workload
  scope                = each.value.id
  role_definition_name = "Role Based Access Control Administrator"
  principal_id         = azurerm_user_assigned_identity.jenkins.principal_id
  principal_type       = "ServicePrincipal"
  condition_version    = "2.0"
  condition            = local.rbac_condition
}

# Registry: push images and let AKS kubelet identities be granted AcrPull only
data "azurerm_container_registry" "acr" {
  name                = var.acr_name
  resource_group_name = var.acr_resource_group
}

resource "azurerm_role_assignment" "acr_push" {
  scope                = data.azurerm_container_registry.acr.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.jenkins.principal_id
  principal_type       = "ServicePrincipal"
}

# Image builds run as ACR Tasks (az acr build) and `latest` is an in-registry import (az acr import)
resource "azurerm_role_assignment" "acr_tasks" {
  scope                = data.azurerm_container_registry.acr.id
  role_definition_name = "Container Registry Tasks Contributor"
  principal_id         = azurerm_user_assigned_identity.jenkins.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "acr_import" {
  scope                = data.azurerm_container_registry.acr.id
  role_definition_name = "Container Registry Data Importer and Data Reader"
  principal_id         = azurerm_user_assigned_identity.jenkins.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "acr_rbac_admin" {
  scope                = data.azurerm_container_registry.acr.id
  role_definition_name = "Role Based Access Control Administrator"
  principal_id         = azurerm_user_assigned_identity.jenkins.principal_id
  principal_type       = "ServicePrincipal"
  condition_version    = "2.0"
  condition            = local.acr_pull_only_condition
}

# ---------- Terraform state container for the main stack
data "azurerm_storage_account" "tfstate" {
  name                = var.tfstate_account
  resource_group_name = var.tfstate_resource_group
}

resource "azurerm_storage_container" "corportal" {
  name                  = "corportal"
  storage_account_id    = data.azurerm_storage_account.tfstate.id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "tfstate" {
  scope                = azurerm_storage_container.corportal.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.jenkins.principal_id
  principal_type       = "ServicePrincipal"
}
