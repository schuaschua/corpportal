# Front Door Standard (P-7): one origin per enabled region (Kong's public IP DNS name), active-
# passive by priority. Kong accepts only requests carrying this profile's X-Azure-FDID.

terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm" }
  }
}

variable "name_suffix" { type = string }
variable "resource_group_name" { type = string }
variable "origins" {
  type = map(object({ host_name = string, priority = number }))
}
variable "tags" { type = map(string) }

resource "azurerm_cdn_frontdoor_profile" "this" {
  name                     = "afd-corportal-${var.name_suffix}"
  resource_group_name      = var.resource_group_name
  sku_name                 = "Standard_AzureFrontDoor"
  response_timeout_seconds = 60
  tags                     = var.tags
}

resource "azurerm_cdn_frontdoor_endpoint" "this" {
  name                     = "fde-corportal-${var.name_suffix}"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.this.id
  tags                     = var.tags
}

resource "azurerm_cdn_frontdoor_origin_group" "kong" {
  name                     = "og-corportal-kong"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.this.id
  session_affinity_enabled = false

  load_balancing {
    sample_size                 = 4
    successful_samples_required = 3
  }

  health_probe {
    protocol            = "Http"
    path                = "/healthz"
    request_type        = "HEAD"
    interval_in_seconds = 30
  }
}

resource "azurerm_cdn_frontdoor_origin" "region" {
  for_each                       = var.origins
  name                           = "origin-${each.key}"
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.kong.id
  enabled                        = true
  host_name                      = each.value.host_name
  origin_host_header             = each.value.host_name
  http_port                      = 80
  https_port                     = 443
  priority                       = each.value.priority
  weight                         = 1000
  certificate_name_check_enabled = true
}

resource "azurerm_cdn_frontdoor_route" "all" {
  name                          = "route-corportal"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.this.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.kong.id
  cdn_frontdoor_origin_ids      = [for o in azurerm_cdn_frontdoor_origin.region : o.id]
  patterns_to_match             = ["/*"]
  supported_protocols           = ["Http", "Https"]
  forwarding_protocol           = "HttpOnly" # Kong listens on 80 behind the origin NSG
  https_redirect_enabled        = true
  link_to_default_domain        = true
}

output "front_door_id" { value = azurerm_cdn_frontdoor_profile.this.resource_guid }
output "endpoint_hostname" { value = azurerm_cdn_frontdoor_endpoint.this.host_name }
output "origin_hosts" { value = { for k, o in azurerm_cdn_frontdoor_origin.region : k => o.host_name } }
output "sku" { value = azurerm_cdn_frontdoor_profile.this.sku_name }

output "tagged" {
  value = {
    profile  = azurerm_cdn_frontdoor_profile.this.tags
    endpoint = azurerm_cdn_frontdoor_endpoint.this.tags
  }
}
