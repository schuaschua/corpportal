# One workload identity per service (and one for HashiCorp Vault), federated to every AKS
# cluster's OIDC issuer for its Kubernetes service account. Only roles on bootstrap's
# allowed-roles list are assigned (the RBAC condition would deny anything else).

terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
  }
}

variable "location" { type = string }
variable "resource_group_name" { type = string }
variable "identities" {
  description = "Identity name -> Kubernetes namespace and service account."
  type        = map(object({ namespace = string, service_account = string }))
}
variable "oidc_issuers" {
  description = "Region key -> AKS OIDC issuer URL."
  type        = map(string)
}
variable "role_assignments" {
  type = map(object({ identity = string, role = string, scope = string }))
  validation {
    condition = alltrue([for a in values(var.role_assignments) : contains([
      "AcrPull", "Network Contributor", "Managed Identity Operator", "Private DNS Zone Contributor",
      "Storage Blob Data Contributor", "Key Vault Secrets User", "Key Vault Secrets Officer",
      "Key Vault Crypto User", "Azure Event Hubs Data Sender", "Azure Event Hubs Data Receiver",
    ], a.role)])
    error_message = "Only roles on infra/bootstrap's allowed-roles list can be assigned."
  }
}
variable "tags" { type = map(string) }

locals {
  federations = {
    for pair in setproduct(keys(var.identities), keys(var.oidc_issuers)) :
    "${pair[0]}-${pair[1]}" => { identity = pair[0], region = pair[1] }
  }
}

resource "azurerm_user_assigned_identity" "this" {
  for_each            = var.identities
  name                = "id-corportal-${each.key}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_federated_identity_credential" "this" {
  for_each                  = local.federations
  name                      = "aks-${each.value.region}"
  user_assigned_identity_id = azurerm_user_assigned_identity.this[each.value.identity].id
  issuer                    = var.oidc_issuers[each.value.region]
  subject                   = "system:serviceaccount:${var.identities[each.value.identity].namespace}:${var.identities[each.value.identity].service_account}"
  audience                  = ["api://AzureADTokenExchange"]
}

resource "azurerm_role_assignment" "this" {
  for_each             = var.role_assignments
  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = azurerm_user_assigned_identity.this[each.value.identity].principal_id
  principal_type       = "ServicePrincipal"
}

output "client_ids" { value = { for k, i in azurerm_user_assigned_identity.this : k => i.client_id } }
output "subjects" { value = { for k, f in azurerm_federated_identity_credential.this : k => f.subject } }

output "tagged" {
  value = { for k, i in azurerm_user_assigned_identity.this : "id-${k}" => i.tags }
}
