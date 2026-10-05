# AKS per region: node auto-provisioning (Karpenter) on Azure CNI Overlay + Cilium, managed
# Istio add-on, OIDC issuer + workload identity, one regular B2s system node, Entra-only
# access (local accounts off), API server limited to the Jenkins VM, our own kubelet identity
# with AcrPull on exampleacr.
# Also Kong's static public IP (the Front Door origin), in this resource group.

terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
  }
}

variable "region_key" { type = string }
variable "location" { type = string }
variable "resource_group_name" { type = string }
variable "name_suffix" { type = string }
variable "subnet_id" { type = string }
variable "system_vm_size" { type = string }
variable "kubernetes_version" { type = string }
variable "istio_revision" { type = string }
variable "authorized_ip_ranges" { type = list(string) }
variable "aks_admin_group_object_ids" { type = list(string) }
variable "tenant_id" { type = string }
variable "acr_id" { type = string }
variable "tags" { type = map(string) }

locals {
  name       = "aks-corportal-${var.region_key}"
  kong_label = "corportal-${var.name_suffix}-${var.region_key}"
}

# Control plane identity, created first so its subnet rights exist before the cluster.
resource "azurerm_user_assigned_identity" "cluster" {
  name                = "id-corportal-aks-${var.region_key}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_role_assignment" "cluster_subnet" {
  scope                = var.subnet_id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.cluster.principal_id
  principal_type       = "ServicePrincipal"
}

# Kubelet identity, ours rather than AKS-generated, so AcrPull can be granted before the first
# image pull. The control plane must be Managed Identity Operator on it (bootstrap allows it).
resource "azurerm_user_assigned_identity" "kubelet" {
  name                = "id-corportal-aks-${var.region_key}-kubelet"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_role_assignment" "cluster_kubelet_operator" {
  scope                = azurerm_user_assigned_identity.kubelet.id
  role_definition_name = "Managed Identity Operator"
  principal_id         = azurerm_user_assigned_identity.cluster.principal_id
  principal_type       = "ServicePrincipal"
}

# The kubelet pulls from the existing registry (bootstrap allows AcrPull only).
resource "azurerm_role_assignment" "acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.kubelet.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_public_ip" "kong" {
  name                = "pip-corportal-kong-${var.region_key}"
  location            = var.location
  resource_group_name = var.resource_group_name
  allocation_method   = "Static"
  sku                 = "Standard"
  domain_name_label   = local.kong_label
  tags                = var.tags
}

resource "azurerm_role_assignment" "cluster_kong_ip" {
  scope                = azurerm_public_ip.kong.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.cluster.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_kubernetes_cluster" "this" {
  name                      = local.name
  location                  = var.location
  resource_group_name       = var.resource_group_name
  dns_prefix                = "corportal-${var.region_key}"
  kubernetes_version        = var.kubernetes_version
  sku_tier                  = "Free"
  oidc_issuer_enabled       = true
  workload_identity_enabled = true
  local_account_disabled    = true
  azure_policy_enabled      = false
  tags                      = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.cluster.id]
  }

  kubelet_identity {
    client_id                 = azurerm_user_assigned_identity.kubelet.client_id
    object_id                 = azurerm_user_assigned_identity.kubelet.principal_id
    user_assigned_identity_id = azurerm_user_assigned_identity.kubelet.id
  }

  default_node_pool {
    name                         = "system"
    vm_size                      = var.system_vm_size
    node_count                   = 1
    vnet_subnet_id               = var.subnet_id
    os_disk_type                 = "Managed"
    max_pods                     = 110
    only_critical_addons_enabled = false # the services may share the one regular node
    temporary_name_for_rotation  = "systemtmp"
    tags                         = var.tags

    upgrade_settings {
      max_surge = "10%"
    }
  }

  # Node auto-provisioning: Karpenter adds (spot) nodes for the services (stack.md).
  node_provisioning_profile {
    mode = "Auto"
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    pod_cidr            = "192.168.0.0/16"
    service_cidr        = "172.16.0.0/16"
    dns_service_ip      = "172.16.0.10"
    load_balancer_sku   = "standard"
    outbound_type       = "loadBalancer"
  }

  service_mesh_profile {
    mode                             = "Istio"
    revisions                        = [var.istio_revision]
    internal_ingress_gateway_enabled = false
    external_ingress_gateway_enabled = false
  }

  api_server_access_profile {
    authorized_ip_ranges = var.authorized_ip_ranges
  }

  azure_active_directory_role_based_access_control {
    tenant_id              = var.tenant_id
    admin_group_object_ids = var.aks_admin_group_object_ids
    azure_rbac_enabled     = false
  }

  depends_on = [
    azurerm_role_assignment.cluster_subnet,
    azurerm_role_assignment.cluster_kubelet_operator,
    azurerm_role_assignment.acr_pull,
    # Destroy order: the cluster (and Kong's load balancer on this IP) goes before the IP and
    # the cluster's rights on it; otherwise Azure refuses to delete an IP still in use.
    azurerm_public_ip.kong,
    azurerm_role_assignment.cluster_kong_ip,
  ]
}

output "name" { value = azurerm_kubernetes_cluster.this.name }
output "id" { value = azurerm_kubernetes_cluster.this.id }
output "location" { value = azurerm_kubernetes_cluster.this.location }
output "resource_group_name" { value = var.resource_group_name }
output "fqdn" { value = azurerm_kubernetes_cluster.this.fqdn }
output "oidc_issuer_url" { value = azurerm_kubernetes_cluster.this.oidc_issuer_url }
output "kong_ip_address" { value = azurerm_public_ip.kong.ip_address }
output "kong_fqdn" { value = "${local.kong_label}.${var.location}.cloudapp.azure.com" }

output "posture" {
  description = "Facts the tests check."
  value = {
    network_plugin_mode = azurerm_kubernetes_cluster.this.network_profile[0].network_plugin_mode
    network_data_plane  = azurerm_kubernetes_cluster.this.network_profile[0].network_data_plane
    node_provisioning   = azurerm_kubernetes_cluster.this.node_provisioning_profile[0].mode
    istio               = azurerm_kubernetes_cluster.this.service_mesh_profile[0].mode
    workload_identity   = azurerm_kubernetes_cluster.this.workload_identity_enabled
    local_accounts_off  = azurerm_kubernetes_cluster.this.local_account_disabled
    system_vm_size      = azurerm_kubernetes_cluster.this.default_node_pool[0].vm_size
    authorized_ips      = azurerm_kubernetes_cluster.this.api_server_access_profile[0].authorized_ip_ranges
  }
}

output "tagged" {
  value = {
    cluster          = azurerm_kubernetes_cluster.this.tags
    cluster_identity = azurerm_user_assigned_identity.cluster.tags
    kubelet_identity = azurerm_user_assigned_identity.kubelet.tags
    kong_ip          = azurerm_public_ip.kong.tags
  }
}
