# The data services (P-5: private endpoints + private DNS, public network access off, no
# shared keys or SQL logins; P-3): ADLS Gen2, Event Hubs Standard (1 TU), Key Vault (RBAC),
# Azure SQL Basic, and, behind enable_sql_failover, a region 2 server and a failover group.
# Key Vault also holds HashiCorp Vault's auto-unseal key. Its firewall admits only the Jenkins
# VM's public IP (Jenkins writes the key and Vault's init secrets from outside the VNet); the
# workloads use the private endpoint.

terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
    time    = { source = "hashicorp/time" }
  }
}

variable "name_suffix" { type = string }
variable "location" { type = string }
variable "resource_group_name" { type = string }
variable "private_endpoint_subnet_id" { type = string }
variable "vnet_ids" { type = map(string) }
variable "tenant_id" { type = string }
variable "sql_admin_login" { type = string }
variable "sql_admin_object_id" { type = string }
variable "enable_sql_failover" { type = bool }
variable "failover_location" { type = string }
variable "failover_resource_group" { type = string }
variable "jenkins_ip_cidr" {
  description = "The Jenkins VM's public IP as a /32: the only public address Key Vault admits."
  type        = string
}
variable "jenkins_object_id" {
  description = "Object ID of id-corportal-jenkins (Key Vault Crypto Officer: the unseal key; Secrets Officer: Vault's root token, recovery key, Grafana admin)."
  type        = string
}
variable "tags" { type = map(string) }

locals {
  dns_zones = {
    blob       = "privatelink.blob.core.windows.net"
    dfs        = "privatelink.dfs.core.windows.net"
    sql        = "privatelink.database.windows.net"
    vault      = "privatelink.vaultcore.azure.net"
    servicebus = "privatelink.servicebus.windows.net"
  }

  zone_links = {
    for pair in setproduct(keys(local.dns_zones), keys(var.vnet_ids)) :
    "${pair[0]}-${pair[1]}" => { zone = pair[0], vnet = pair[1] }
  }

  private_endpoints = merge(
    {
      "st-blob" = { resource_id = azurerm_storage_account.lake.id, subresource = "blob", zone = "blob" }
      "st-dfs"  = { resource_id = azurerm_storage_account.lake.id, subresource = "dfs", zone = "dfs" }
      "sql"     = { resource_id = azurerm_mssql_server.primary.id, subresource = "sqlServer", zone = "sql" }
      "kv"      = { resource_id = azurerm_key_vault.this.id, subresource = "vault", zone = "vault" }
      "evhns"   = { resource_id = azurerm_eventhub_namespace.this.id, subresource = "namespace", zone = "servicebus" }
    },
    var.enable_sql_failover ? {
      "sql-secondary" = { resource_id = azurerm_mssql_server.secondary[0].id, subresource = "sqlServer", zone = "sql" }
    } : {}
  )

  sql_server_name   = "sql-corportal-${var.name_suffix}"
  failover_name     = "fog-corportal-${var.name_suffix}"
  sql_database_name = "corportal"
}

# ---------- private DNS
resource "azurerm_private_dns_zone" "this" {
  for_each            = local.dns_zones
  name                = each.value
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "this" {
  for_each              = local.zone_links
  name                  = "link-${each.value.vnet}"
  resource_group_name   = var.resource_group_name
  private_dns_zone_name = azurerm_private_dns_zone.this[each.value.zone].name
  virtual_network_id    = var.vnet_ids[each.value.vnet]
  registration_enabled  = false
  tags                  = var.tags
}

# ---------- ADLS Gen2
resource "azurerm_storage_account" "lake" {
  name                             = "stcorportallake${var.name_suffix}"
  location                         = var.location
  resource_group_name              = var.resource_group_name
  account_kind                     = "StorageV2"
  account_tier                     = "Standard"
  account_replication_type         = "LRS"
  is_hns_enabled                   = true
  min_tls_version                  = "TLS1_2"
  https_traffic_only_enabled       = true
  shared_access_key_enabled        = false
  default_to_oauth_authentication  = true
  public_network_access_enabled    = false
  allow_nested_items_to_be_public  = false
  cross_tenant_replication_enabled = false
  local_user_enabled               = false
  tags                             = var.tags

  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
  }

  blob_properties {
    delete_retention_policy {
      days = 7
    }
  }
}

resource "azurerm_storage_container" "lake" {
  name                  = "lake"
  storage_account_id    = azurerm_storage_account.lake.id
  container_access_type = "private"
}

# ---------- Event Hubs Standard, 1 TU, Kafka endpoint (Databricks reads it)
resource "azurerm_eventhub_namespace" "this" {
  name                          = "evhns-corportal-${var.name_suffix}"
  location                      = var.location
  resource_group_name           = var.resource_group_name
  sku                           = "Standard"
  capacity                      = 1
  auto_inflate_enabled          = false
  local_authentication_enabled  = false
  public_network_access_enabled = false
  minimum_tls_version           = "1.2"
  tags                          = var.tags
}

resource "azurerm_eventhub" "portal_events" {
  name              = "portal-events"
  namespace_id      = azurerm_eventhub_namespace.this.id
  partition_count   = 2
  message_retention = 7
}

# ---------- Key Vault (RBAC; Vault's auto-unseal key and root credentials)
resource "azurerm_key_vault" "this" {
  name                       = "kv-corportal-${var.name_suffix}"
  location                   = var.location
  resource_group_name        = var.resource_group_name
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  # On only so the firewall's single IP rule applies: everything else is denied, and the
  # workloads come in through the private endpoint (P-5, the Jenkins IP is the one exception).
  public_network_access_enabled = true
  soft_delete_retention_days    = 7
  purge_protection_enabled      = false # PoC: destroyed on 4 Oct (P-9)
  tags                          = var.tags

  network_acls {
    default_action = "Deny"
    bypass         = "None"
    ip_rules       = [var.jenkins_ip_cidr]
  }
}

# Jenkins writes Vault's root token and recovery key and the Grafana admin password (P-3).
resource "azurerm_role_assignment" "jenkins_kv_secrets" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = var.jenkins_object_id
  principal_type       = "ServicePrincipal"
}

# Jenkins creates Vault's unseal key below.
resource "azurerm_role_assignment" "jenkins_kv_crypto" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Crypto Officer"
  principal_id         = var.jenkins_object_id
  principal_type       = "ServicePrincipal"
}

# New data-plane role assignments take a few minutes to reach Key Vault.
resource "time_sleep" "kv_rbac_propagation" {
  create_duration = "120s"
  depends_on      = [azurerm_role_assignment.jenkins_kv_crypto, azurerm_role_assignment.jenkins_kv_secrets]
}

# HashiCorp Vault's auto-unseal key (seal "azurekeyvault"). id-corportal-vault has Key Vault
# Crypto User on this vault (root module, `identity`).
resource "azurerm_key_vault_key" "vault_unseal" {
  depends_on   = [time_sleep.kv_rbac_propagation]
  name         = "vault-unseal"
  key_vault_id = azurerm_key_vault.this.id
  key_type     = "RSA"
  key_size     = 2048
  key_opts     = ["wrapKey", "unwrapKey"]
  tags         = var.tags
}

# ---------- Azure SQL: Entra-only admin, no public access
resource "azurerm_mssql_server" "primary" {
  name                          = local.sql_server_name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  version                       = "12.0"
  minimum_tls_version           = "1.2"
  public_network_access_enabled = false
  tags                          = var.tags

  azuread_administrator {
    login_username              = var.sql_admin_login
    object_id                   = var.sql_admin_object_id
    tenant_id                   = var.tenant_id
    azuread_authentication_only = true
  }
}

resource "azurerm_mssql_database" "corportal" {
  name                 = local.sql_database_name
  server_id            = azurerm_mssql_server.primary.id
  sku_name             = var.enable_sql_failover ? "S0" : "Basic"
  max_size_gb          = 2
  storage_account_type = "Local"
  tags                 = var.tags
}

resource "azurerm_mssql_server" "secondary" {
  count                         = var.enable_sql_failover ? 1 : 0
  name                          = "${local.sql_server_name}-2"
  location                      = var.failover_location
  resource_group_name           = var.failover_resource_group
  version                       = "12.0"
  minimum_tls_version           = "1.2"
  public_network_access_enabled = false
  tags                          = var.tags

  azuread_administrator {
    login_username              = var.sql_admin_login
    object_id                   = var.sql_admin_object_id
    tenant_id                   = var.tenant_id
    azuread_authentication_only = true
  }
}

resource "azurerm_mssql_failover_group" "this" {
  count     = var.enable_sql_failover ? 1 : 0
  name      = local.failover_name
  server_id = azurerm_mssql_server.primary.id
  databases = [azurerm_mssql_database.corportal.id]
  tags      = var.tags

  partner_server {
    id = azurerm_mssql_server.secondary[0].id
  }

  read_write_endpoint_failover_policy {
    mode = "Manual" # the dry run fails over by hand
  }
}

# ---------- private endpoints
resource "azurerm_private_endpoint" "this" {
  for_each            = local.private_endpoints
  name                = "pe-corportal-${each.key}"
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = var.private_endpoint_subnet_id
  tags                = var.tags

  private_service_connection {
    name                           = "psc-corportal-${each.key}"
    private_connection_resource_id = each.value.resource_id
    subresource_names              = [each.value.subresource]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "default"
    private_dns_zone_ids = [azurerm_private_dns_zone.this[each.value.zone].id]
  }
}

# ---------- outputs
output "storage_account_id" { value = azurerm_storage_account.lake.id }
output "storage_account_name" { value = azurerm_storage_account.lake.name }
output "eventhub_namespace_id" { value = azurerm_eventhub_namespace.this.id }
output "eventhub_namespace_fqdn" { value = "${azurerm_eventhub_namespace.this.name}.servicebus.windows.net" }
output "key_vault_id" { value = azurerm_key_vault.this.id }
output "key_vault_uri" { value = "https://${azurerm_key_vault.this.name}.vault.azure.net/" }
output "key_vault_name" { value = azurerm_key_vault.this.name }
output "vault_unseal_key_name" { value = azurerm_key_vault_key.vault_unseal.name }

output "key_vault_posture" {
  description = "Key Vault firewall and unseal key facts (tests: P-5 exception for Jenkins)."
  value = {
    public_network_access = azurerm_key_vault.this.public_network_access_enabled
    default_action        = azurerm_key_vault.this.network_acls[0].default_action
    bypass                = azurerm_key_vault.this.network_acls[0].bypass
    ip_rules              = azurerm_key_vault.this.network_acls[0].ip_rules
    virtual_network_rules = azurerm_key_vault.this.network_acls[0].virtual_network_subnet_ids
    unseal_key_type       = azurerm_key_vault_key.vault_unseal.key_type
    unseal_key_opts       = azurerm_key_vault_key.vault_unseal.key_opts
    jenkins_secrets_role  = azurerm_role_assignment.jenkins_kv_secrets.role_definition_name
    jenkins_crypto_role   = azurerm_role_assignment.jenkins_kv_crypto.role_definition_name
  }
}
output "sql_database_name" { value = azurerm_mssql_database.corportal.name }

output "sql_fqdn" {
  description = "Failover group listener when enable_sql_failover, else the primary server."
  value       = var.enable_sql_failover ? "${local.failover_name}.database.windows.net" : "${local.sql_server_name}.database.windows.net"
}

output "security_posture" {
  description = "Lockdown facts (tests: P-3 / P-5)."
  value = {
    public_network_access = {
      storage   = azurerm_storage_account.lake.public_network_access_enabled
      sql       = azurerm_mssql_server.primary.public_network_access_enabled
      key_vault = azurerm_key_vault.this.public_network_access_enabled
      eventhubs = azurerm_eventhub_namespace.this.public_network_access_enabled
    }
    storage_shared_key       = azurerm_storage_account.lake.shared_access_key_enabled
    eventhubs_local_auth     = azurerm_eventhub_namespace.this.local_authentication_enabled
    sql_entra_only           = azurerm_mssql_server.primary.azuread_administrator[0].azuread_authentication_only
    private_endpoints        = { for k, pe in azurerm_private_endpoint.this : k => pe.private_service_connection[0].subresource_names[0] }
    private_dns_zones        = sort([for z in azurerm_private_dns_zone.this : z.name])
    sql_secondary_location   = var.enable_sql_failover ? azurerm_mssql_server.secondary[0].location : null
    sql_failover_group_count = length(azurerm_mssql_failover_group.this)
    sql_sku                  = azurerm_mssql_database.corportal.sku_name
  }
}

output "tagged" {
  description = "Tags of every taggable resource in this module (tests: P-9 tag set)."
  value = merge(
    { for k, z in azurerm_private_dns_zone.this : "dns-${k}" => z.tags },
    { for k, l in azurerm_private_dns_zone_virtual_network_link.this : "dnslink-${k}" => l.tags },
    { for k, pe in azurerm_private_endpoint.this : "pe-${k}" => pe.tags },
    {
      storage   = azurerm_storage_account.lake.tags
      eventhubs = azurerm_eventhub_namespace.this.tags
      key_vault = azurerm_key_vault.this.tags
      kv_key    = azurerm_key_vault_key.vault_unseal.tags
      sql       = azurerm_mssql_server.primary.tags
      sql_db    = azurerm_mssql_database.corportal.tags
    },
    var.enable_sql_failover ? {
      sql_secondary = azurerm_mssql_server.secondary[0].tags
      sql_fog       = azurerm_mssql_failover_group.this[0].tags
    } : {}
  )
}
