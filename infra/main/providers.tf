provider "azurerm" {
  # Jenkins: ARM_USE_MSI + ARM_CLIENT_ID/ARM_TENANT_ID/ARM_SUBSCRIPTION_ID (id-corportal-jenkins).
  subscription_id = var.subscription_id

  # Subscription-level provider registration is the Owner's job (infra/bootstrap); Jenkins
  # only has rights inside the corportal resource groups.
  resource_provider_registrations = "none"
  storage_use_azuread             = true

  features {
    key_vault {
      purge_soft_delete_on_destroy = false
    }
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
    storage {
      # Storage is private (P-5) and Jenkins is outside the VNet: manage it through ARM only.
      data_plane_available = false
    }
  }
}

# Unity Catalog (unity_catalog.tf) and, when var.databricks_metastore_id is set, the metastore
# assignment. Jenkins' identity created the workspace, so it is a workspace admin.
provider "databricks" {
  host                        = module.databricks.workspace_url
  azure_workspace_resource_id = module.databricks.workspace_resource_id
  auth_type                   = "azure-msi"
}
