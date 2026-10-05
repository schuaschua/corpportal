# Offline proof of infra/main (no Azure credentials, no cloud calls): mocked providers, plan only.
#   terraform -chdir=infra/main init -backend=false && terraform -chdir=infra/main test

mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000001"
      subscription_id = "00000000-0000-0000-0000-000000000002"
      object_id       = "00000000-0000-0000-0000-000000000003"
      client_id       = "00000000-0000-0000-0000-000000000004"
    }
  }
  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/rg-corportal-mock"
      location = "westus3"
    }
  }
  mock_data "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000002/resourceGroups/rg-example-shared/providers/Microsoft.ContainerRegistry/registries/exampleacr"
      login_server = "exampleacr.azurecr.io"
    }
  }
}

mock_provider "databricks" {}

variables {
  jenkins_public_ip          = "203.0.113.10"
  aks_admin_group_object_ids = ["00000000-0000-0000-0000-0000000000aa"]
}

run "default_one_region" {
  command = plan

  assert {
    condition     = keys(module.aks) == ["primary"] && keys(module.network) == ["primary"]
    error_message = "Defaults must build one region only."
  }
  assert {
    condition     = module.aks["primary"].location == "westus3"
    error_message = "Region 1 must be West US 3 by default (P-11)."
  }
  assert {
    condition = (
      module.aks["primary"].posture.network_plugin_mode == "overlay" &&
      module.aks["primary"].posture.network_data_plane == "cilium" &&
      module.aks["primary"].posture.node_provisioning == "Auto" &&
      module.aks["primary"].posture.istio == "Istio" &&
      module.aks["primary"].posture.workload_identity &&
      module.aks["primary"].posture.local_accounts_off &&
      module.aks["primary"].posture.system_vm_size == "Standard_B2s" &&
      module.aks["primary"].posture.authorized_ips == toset(["203.0.113.10/32", "203.0.113.5/32"])
    )
    error_message = "AKS must use CNI Overlay + Cilium, node auto-provisioning, managed Istio, workload identity, one B2s system node and only the Jenkins IP."
  }
  assert {
    condition     = keys(module.edge[0].origin_hosts) == ["primary"] && module.edge[0].sku == "Standard_AzureFrontDoor"
    error_message = "Front Door Standard with exactly one origin by default."
  }
  assert {
    condition     = module.data.security_posture.sql_failover_group_count == 0 && module.data.security_posture.sql_secondary_location == null
    error_message = "No SQL failover group or secondary server by default."
  }
  assert {
    condition     = module.data.security_posture.sql_sku == "Basic"
    error_message = "Azure SQL is Basic by default."
  }
  assert {
    condition     = module.databricks.sku == "premium" && module.databricks.no_public_ip
    error_message = "Databricks must be Premium and VNet-injected without public IPs."
  }
  assert {
    condition     = length(azurerm_virtual_network_peering.primary_to_secondary) == 0
    error_message = "No peering without region 2."
  }
}

run "saturday_second_region" {
  command = plan

  variables {
    secondary_region_enabled = true
  }

  assert {
    condition     = keys(module.aks) == ["primary", "secondary"] && keys(module.network) == ["primary", "secondary"]
    error_message = "secondary_region_enabled must add region 2's network and AKS."
  }
  assert {
    condition     = module.aks["secondary"].location == "northcentralus"
    error_message = "Region 2 must be North Central US by default (P-11)."
  }
  assert {
    condition     = keys(module.edge[0].origin_hosts) == ["primary", "secondary"]
    error_message = "Front Door must have one origin per region."
  }
  assert {
    condition     = length(azurerm_virtual_network_peering.primary_to_secondary) == 1 && length(azurerm_virtual_network_peering.secondary_to_primary) == 1
    error_message = "Region 2 must be peered to reach the private endpoints."
  }
  assert {
    condition     = length(module.identity.subjects) == 12
    error_message = "Every workload identity (5 services + Vault) must be federated to both clusters."
  }
}

run "sql_failover_dry_run" {
  command = plan

  variables {
    enable_sql_failover = true
  }

  assert {
    condition     = module.data.security_posture.sql_failover_group_count == 1
    error_message = "enable_sql_failover must add a failover group."
  }
  assert {
    condition     = module.data.security_posture.sql_secondary_location == "northcentralus"
    error_message = "The secondary SQL server must be in region 2."
  }
  assert {
    condition     = output.sql_fqdn == "fog-corportal-poc01.database.windows.net"
    error_message = "sql_fqdn must be the failover group listener."
  }
  assert {
    condition     = module.data.security_posture.private_endpoints["sql-secondary"] == "sqlServer"
    error_message = "The secondary SQL server must also be private."
  }
  assert {
    condition     = module.data.security_posture.sql_sku != "Basic"
    error_message = "The failover dry run upgrades the SQL tier."
  }
}

run "lockdown" {
  command = plan

  assert {
    condition = alltrue([
      for k, v in module.data.security_posture.public_network_access : v == false if k != "key_vault"
    ])
    error_message = "ADLS, SQL and Event Hubs must have public network access off (P-5; Key Vault: see key_vault_unseal)."
  }
  assert {
    condition = (
      module.data.security_posture.private_endpoints == {
        "st-blob" = "blob", "st-dfs" = "dfs", "sql" = "sqlServer", "kv" = "vault", "evhns" = "namespace"
      }
    )
    error_message = "The four data services must each have a private endpoint (P-5)."
  }
  assert {
    condition     = length(module.data.security_posture.private_dns_zones) == 5
    error_message = "Each private endpoint needs its private DNS zone."
  }
  assert {
    condition = (
      module.data.security_posture.storage_shared_key == false &&
      module.data.security_posture.eventhubs_local_auth == false &&
      module.data.security_posture.sql_entra_only
    )
    error_message = "No shared keys, SAS or SQL logins: storage shared key off, Event Hubs local auth off, SQL Entra-only (P-3)."
  }
  assert {
    condition     = output.sql_fqdn == "sql-corportal-poc01.database.windows.net"
    error_message = "Without failover, sql_fqdn is the primary server."
  }
}

run "tags_everywhere" {
  command = plan

  variables {
    secondary_region_enabled = true
    enable_sql_failover      = true
  }

  assert {
    condition = alltrue([
      for tags in concat(
        flatten([for n in values(module.network) : values(n.tagged)]),
        flatten([for a in values(module.aks) : values(a.tagged)]),
        values(module.data.tagged),
        values(module.databricks.tagged),
        values(module.edge[0].tagged),
        values(module.identity.tagged),
      ) :
      length(setsubtract(["application", "costCentre", "dataClassification", "environment", "owner", "destroyBy"], keys(tags))) == 0
    ])
    error_message = "Every taggable resource must carry the six tags (P-9)."
  }
}

run "key_vault_unseal" {
  command = plan

  assert {
    condition     = output.vault_unseal_key_name == "vault-unseal" && module.data.key_vault_posture.unseal_key_type == "RSA"
    error_message = "Terraform must create Vault's RSA auto-unseal key in Key Vault."
  }
  assert {
    condition     = toset(module.data.key_vault_posture.unseal_key_opts) == toset(["wrapKey", "unwrapKey"])
    error_message = "The unseal key must only wrap and unwrap."
  }
  assert {
    condition = (
      module.data.key_vault_posture.default_action == "Deny" &&
      module.data.key_vault_posture.bypass == "None" &&
      toset(module.data.key_vault_posture.ip_rules) == toset(["203.0.113.10/32"]) &&
      length(coalesce(module.data.key_vault_posture.virtual_network_rules, [])) == 0
    )
    error_message = "Key Vault's firewall must deny everything but the Jenkins VM IP (P-5 exception)."
  }
  assert {
    condition     = module.data.security_posture.private_endpoints["kv"] == "vault"
    error_message = "Workloads must still reach Key Vault through its private endpoint (P-5)."
  }
  assert {
    condition     = module.data.key_vault_posture.jenkins_secrets_role == "Key Vault Secrets Officer"
    error_message = "Jenkins must be able to write Vault's init secrets to Key Vault (P-3)."
  }
  assert {
    condition     = module.data.key_vault_posture.jenkins_crypto_role == "Key Vault Crypto Officer"
    error_message = "Jenkins must be able to create Vault's unseal key without a manual grant."
  }
}

run "dev_environment" {
  command = plan

  variables {
    environment              = "dev"
    name_suffix              = "poc01d"
    primary_region           = "westus2"
    resource_group_primary   = "rg-corportal-dev-primary"
    resource_group_secondary = "rg-corportal-dev-primary"
    resource_group_data      = "rg-corportal-dev-data"
    front_door_enabled       = false
  }

  assert {
    condition     = length(module.edge) == 0 && output.front_door_id == ""
    error_message = "dev has no Front Door: users reach Kong's public IP."
  }
  assert {
    condition     = keys(module.aks) == ["primary"] && module.aks["primary"].location == "westus2"
    error_message = "dev is one region, westus2."
  }
  assert {
    condition     = module.aks["primary"].kong_fqdn == "corportal-poc01d-primary.westus2.cloudapp.azure.com"
    error_message = "dev's entry point is Kong's DNS name (the Entra redirect URI and the TLS certificate use it)."
  }
  assert {
    condition     = local.tags.environment == "dev"
    error_message = "Resources are tagged with their environment."
  }
}
