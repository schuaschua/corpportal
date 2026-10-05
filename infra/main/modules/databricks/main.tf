# Azure Databricks Premium, VNet-injected with no public IP (egress through the network
# module's NAT gateway), and the Unity Catalog Access Connector with Storage Blob Data
# Contributor on ADLS and Event Hubs Data Receiver (the bundle's Kafka read). The connector runs
# as a user-assigned identity so its client ID is known (db-init makes it a SQL user in
# pipeline_writer). No clusters here: the bundle owns single-node job clusters (P-9).

terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
  }
}

variable "name_suffix" { type = string }
variable "location" { type = string }
variable "resource_group_name" { type = string }
variable "virtual_network_id" { type = string }
variable "host_subnet" { type = object({ name = string, nsg_association_id = string }) }
variable "container_subnet" { type = object({ name = string, nsg_association_id = string }) }
variable "storage_account_id" { type = string }
variable "eventhub_namespace_id" { type = string }
variable "tags" { type = map(string) }

resource "azurerm_databricks_workspace" "this" {
  name                                  = "dbw-corportal-${var.name_suffix}"
  location                              = var.location
  resource_group_name                   = var.resource_group_name
  sku                                   = "premium"
  managed_resource_group_name           = "rg-corportal-databricks-managed"
  public_network_access_enabled         = true # workspace UI/API; compute has no public IP
  network_security_group_rules_required = "AllRules"
  tags                                  = var.tags

  custom_parameters {
    no_public_ip                                         = true
    virtual_network_id                                   = var.virtual_network_id
    public_subnet_name                                   = var.host_subnet.name
    private_subnet_name                                  = var.container_subnet.name
    public_subnet_network_security_group_association_id  = var.host_subnet.nsg_association_id
    private_subnet_network_security_group_association_id = var.container_subnet.nsg_association_id
  }
}

resource "azurerm_user_assigned_identity" "connector" {
  name                = "id-corportal-dbac-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_databricks_access_connector" "this" {
  name                = "dbac-corportal-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.connector.id]
  }
}

resource "azurerm_role_assignment" "lake" {
  scope                = var.storage_account_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.connector.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "eventhubs" {
  scope                = var.eventhub_namespace_id
  role_definition_name = "Azure Event Hubs Data Receiver"
  principal_id         = azurerm_user_assigned_identity.connector.principal_id
  principal_type       = "ServicePrincipal"
}

output "workspace_url" { value = azurerm_databricks_workspace.this.workspace_url }
output "workspace_id" { value = azurerm_databricks_workspace.this.workspace_id }
output "workspace_resource_id" { value = azurerm_databricks_workspace.this.id }
output "access_connector_id" { value = azurerm_databricks_access_connector.this.id }
output "access_connector_identity_id" { value = azurerm_user_assigned_identity.connector.id }
output "access_connector_client_id" { value = azurerm_user_assigned_identity.connector.client_id }
output "sku" { value = azurerm_databricks_workspace.this.sku }
output "no_public_ip" { value = azurerm_databricks_workspace.this.custom_parameters[0].no_public_ip }

output "tagged" {
  value = {
    workspace        = azurerm_databricks_workspace.this.tags
    access_connector = azurerm_databricks_access_connector.this.tags
  }
}
