# The corportal platform (piece 6). Applied only by Jenkins (P-2) as id-corportal-jenkins, inside
# the resource groups infra/bootstrap created; it creates no resource groups and assigns only the
# roles bootstrap's condition allows (AcrPull, Network Contributor, Storage Blob Data
# Contributor, Key Vault Crypto/Secrets User, Event Hubs Data Sender/Receiver).

data "azurerm_client_config" "current" {}

data "azurerm_resource_group" "primary" {
  name = var.resource_group_primary
}

data "azurerm_resource_group" "secondary" {
  name = var.resource_group_secondary
}

data "azurerm_resource_group" "data" {
  name = var.resource_group_data
}

data "azurerm_container_registry" "acr" {
  name                = var.acr_name
  resource_group_name = var.acr_resource_group
}

locals {
  # Same tag set as infra/bootstrap (P-9).
  tags = {
    application        = "corportal"
    costCentre         = "poc"
    dataClassification = "synthetic"
    environment        = var.environment
    owner              = "platform-team"
    destroyBy          = "2026-10-04"
  }

  regions = merge(
    {
      primary = {
        location       = var.primary_region
        resource_group = data.azurerm_resource_group.primary.name
        address_space  = "10.10.0.0/16"
        data_subnets   = true # private endpoints + Databricks live in region 1
        priority       = 1
      }
    },
    var.secondary_region_enabled ? {
      secondary = {
        location       = var.secondary_region
        resource_group = data.azurerm_resource_group.secondary.name
        address_space  = "10.20.0.0/16"
        data_subnets   = false
        priority       = 2
      }
    } : {}
  )

  authorized_ip_ranges = concat(["${var.jenkins_public_ip}/32"], var.extra_authorized_ip_ranges)
  sql_admin_object_id  = coalesce(var.sql_admin_object_id, var.aks_admin_group_object_ids[0])
}

module "network" {
  source   = "./modules/network"
  for_each = local.regions

  region_key          = each.key
  location            = each.value.location
  resource_group_name = each.value.resource_group
  address_space       = each.value.address_space
  data_subnets        = each.value.data_subnets
  tags                = local.tags
}

# Region 2 reaches the private endpoints in region 1 over peering.
resource "azurerm_virtual_network_peering" "secondary_to_primary" {
  count                     = var.secondary_region_enabled ? 1 : 0
  name                      = "peer-secondary-to-primary"
  resource_group_name       = local.regions.secondary.resource_group
  virtual_network_name      = module.network["secondary"].vnet_name
  remote_virtual_network_id = module.network["primary"].vnet_id
  allow_forwarded_traffic   = false
}

resource "azurerm_virtual_network_peering" "primary_to_secondary" {
  count                     = var.secondary_region_enabled ? 1 : 0
  name                      = "peer-primary-to-secondary"
  resource_group_name       = local.regions.primary.resource_group
  virtual_network_name      = module.network["primary"].vnet_name
  remote_virtual_network_id = module.network["secondary"].vnet_id
  allow_forwarded_traffic   = false
}

module "data" {
  source = "./modules/data"

  name_suffix                = var.name_suffix
  location                   = var.primary_region
  resource_group_name        = data.azurerm_resource_group.data.name
  private_endpoint_subnet_id = module.network["primary"].private_endpoint_subnet_id
  vnet_ids                   = { for k, n in module.network : k => n.vnet_id }
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sql_admin_login            = var.sql_admin_login
  sql_admin_object_id        = local.sql_admin_object_id
  enable_sql_failover        = var.enable_sql_failover
  failover_location          = var.secondary_region
  failover_resource_group    = data.azurerm_resource_group.secondary.name
  jenkins_ip_cidr            = "${var.jenkins_public_ip}/32"
  jenkins_object_id          = data.azurerm_client_config.current.object_id
  tags                       = local.tags
}

module "aks" {
  source   = "./modules/aks"
  for_each = local.regions

  region_key                 = each.key
  location                   = each.value.location
  resource_group_name        = each.value.resource_group
  name_suffix                = var.name_suffix
  subnet_id                  = module.network[each.key].aks_subnet_id
  system_vm_size             = var.aks_system_vm_size
  kubernetes_version         = var.kubernetes_version
  istio_revision             = var.istio_revision
  authorized_ip_ranges       = local.authorized_ip_ranges
  aks_admin_group_object_ids = var.aks_admin_group_object_ids
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  acr_id                     = data.azurerm_container_registry.acr.id
  tags                       = local.tags
}

module "databricks" {
  source = "./modules/databricks"

  name_suffix           = var.name_suffix
  location              = var.primary_region
  resource_group_name   = data.azurerm_resource_group.data.name
  virtual_network_id    = module.network["primary"].vnet_id
  host_subnet           = module.network["primary"].databricks_host_subnet
  container_subnet      = module.network["primary"].databricks_container_subnet
  storage_account_id    = module.data.storage_account_id
  eventhub_namespace_id = module.data.eventhub_namespace_id
  tags                  = local.tags
}

resource "databricks_metastore_assignment" "this" {
  count        = var.databricks_metastore_id == "" ? 0 : 1
  metastore_id = var.databricks_metastore_id
  workspace_id = module.databricks.workspace_id
}

module "edge" {
  source = "./modules/edge"
  count  = var.front_door_enabled ? 1 : 0

  name_suffix         = var.name_suffix
  resource_group_name = data.azurerm_resource_group.data.name
  origins = {
    for k, r in local.regions : k => {
      host_name = module.aks[k].kong_fqdn
      priority  = r.priority
    }
  }
  tags = local.tags
}

module "identity" {
  source = "./modules/identity"

  location            = var.primary_region
  resource_group_name = data.azurerm_resource_group.primary.name
  identities = merge(
    { for s in var.services : s => { namespace = "corportal", service_account = s } },
    { vault = { namespace = "vault", service_account = "vault" } }
  )
  oidc_issuers = { for k, a in module.aks : k => a.oidc_issuer_url }
  role_assignments = {
    "outbox-relay/eventhubs-sender" = { identity = "outbox-relay", role = "Azure Event Hubs Data Sender", scope = module.data.eventhub_namespace_id }
    "vault/kv-crypto-user"          = { identity = "vault", role = "Key Vault Crypto User", scope = module.data.key_vault_id }
    "vault/kv-secrets-user"         = { identity = "vault", role = "Key Vault Secrets User", scope = module.data.key_vault_id }
  }
  tags = local.tags
}
