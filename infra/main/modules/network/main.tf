# One VNet per region. Region 1 also has the private endpoint subnet and the two Databricks
# subnets (VNet injection, with a NAT gateway for their egress; nothing else uses the NAT).

terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
  }
}

variable "region_key" { type = string }
variable "location" { type = string }
variable "resource_group_name" { type = string }
variable "address_space" { type = string }
variable "data_subnets" { type = bool }
variable "tags" { type = map(string) }

locals {
  name = "corportal-${var.region_key}"
  databricks_delegation_actions = [
    "Microsoft.Network/virtualNetworks/subnets/join/action",
    "Microsoft.Network/virtualNetworks/subnets/prepareNetworkPolicies/action",
    "Microsoft.Network/virtualNetworks/subnets/unprepareNetworkPolicies/action",
  ]
  databricks_subnets = var.data_subnets ? {
    host      = cidrsubnet(var.address_space, 8, 8)
    container = cidrsubnet(var.address_space, 8, 9)
  } : {}
}

resource "azurerm_virtual_network" "this" {
  name                = "vnet-${local.name}"
  location            = var.location
  resource_group_name = var.resource_group_name
  address_space       = [var.address_space]
  tags                = var.tags
}

# ---------- AKS nodes (pods use the CNI overlay range, not this subnet)
resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [cidrsubnet(var.address_space, 6, 0)]
}

resource "azurerm_network_security_group" "aks" {
  name                = "nsg-${local.name}-aks"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags

  # P-7, network layer: web traffic only from Front Door's back end (Kong also checks X-Azure-FDID).
  security_rule {
    name                       = "allow-frontdoor-http"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["80", "443"]
    source_address_prefix      = "AzureFrontDoor.Backend"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "deny-internet-http"
    priority                   = 200
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_ranges    = ["80", "443"]
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "aks" {
  subnet_id                 = azurerm_subnet.aks.id
  network_security_group_id = azurerm_network_security_group.aks.id
}

# ---------- private endpoints (ADLS, SQL, Key Vault, Event Hubs; P-5)
resource "azurerm_subnet" "private_endpoints" {
  count                           = var.data_subnets ? 1 : 0
  name                            = "snet-private-endpoints"
  resource_group_name             = var.resource_group_name
  virtual_network_name            = azurerm_virtual_network.this.name
  address_prefixes                = [cidrsubnet(var.address_space, 8, 4)]
  default_outbound_access_enabled = false
}

resource "azurerm_network_security_group" "private_endpoints" {
  count               = var.data_subnets ? 1 : 0
  name                = "nsg-${local.name}-pe"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_subnet_network_security_group_association" "private_endpoints" {
  count                     = var.data_subnets ? 1 : 0
  subnet_id                 = azurerm_subnet.private_endpoints[0].id
  network_security_group_id = azurerm_network_security_group.private_endpoints[0].id
}

# ---------- Databricks VNet injection (no public IP; NAT gateway egress)
resource "azurerm_subnet" "databricks" {
  for_each                        = local.databricks_subnets
  name                            = "snet-databricks-${each.key}"
  resource_group_name             = var.resource_group_name
  virtual_network_name            = azurerm_virtual_network.this.name
  address_prefixes                = [each.value]
  default_outbound_access_enabled = false

  delegation {
    name = "databricks"
    service_delegation {
      name    = "Microsoft.Databricks/workspaces"
      actions = local.databricks_delegation_actions
    }
  }
}

resource "azurerm_network_security_group" "databricks" {
  count               = var.data_subnets ? 1 : 0
  name                = "nsg-${local.name}-databricks"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
  # Databricks adds its required rules (network_security_group_rules_required = AllRules).
  lifecycle {
    ignore_changes = [security_rule]
  }
}

resource "azurerm_subnet_network_security_group_association" "databricks" {
  for_each                  = azurerm_subnet.databricks
  subnet_id                 = each.value.id
  network_security_group_id = azurerm_network_security_group.databricks[0].id
}

resource "azurerm_public_ip" "nat" {
  count               = var.data_subnets ? 1 : 0
  name                = "pip-${local.name}-nat"
  location            = var.location
  resource_group_name = var.resource_group_name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

resource "azurerm_nat_gateway" "databricks" {
  count               = var.data_subnets ? 1 : 0
  name                = "ng-${local.name}-databricks"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku_name            = "Standard"
  tags                = var.tags
}

resource "azurerm_nat_gateway_public_ip_association" "databricks" {
  count                = var.data_subnets ? 1 : 0
  nat_gateway_id       = azurerm_nat_gateway.databricks[0].id
  public_ip_address_id = azurerm_public_ip.nat[0].id
}

resource "azurerm_subnet_nat_gateway_association" "databricks" {
  for_each       = azurerm_subnet.databricks
  subnet_id      = each.value.id
  nat_gateway_id = azurerm_nat_gateway.databricks[0].id
}

# ---------- outputs
output "vnet_id" { value = azurerm_virtual_network.this.id }
output "vnet_name" { value = azurerm_virtual_network.this.name }
output "aks_subnet_id" { value = azurerm_subnet.aks.id }

output "private_endpoint_subnet_id" {
  value = var.data_subnets ? azurerm_subnet.private_endpoints[0].id : null
}

output "databricks_host_subnet" {
  value = var.data_subnets ? {
    name               = azurerm_subnet.databricks["host"].name
    nsg_association_id = azurerm_subnet_network_security_group_association.databricks["host"].id
  } : null
}

output "databricks_container_subnet" {
  value = var.data_subnets ? {
    name               = azurerm_subnet.databricks["container"].name
    nsg_association_id = azurerm_subnet_network_security_group_association.databricks["container"].id
  } : null
}

output "tagged" {
  description = "Tags of every taggable resource in this module (tests: P-9 tag set)."
  value = merge(
    {
      vnet    = azurerm_virtual_network.this.tags
      nsg_aks = azurerm_network_security_group.aks.tags
    },
    var.data_subnets ? {
      nsg_pe         = azurerm_network_security_group.private_endpoints[0].tags
      nsg_databricks = azurerm_network_security_group.databricks[0].tags
      pip_nat        = azurerm_public_ip.nat[0].tags
      nat_gateway    = azurerm_nat_gateway.databricks[0].tags
    } : {}
  )
}
