# Read by Jenkins (ci/scripts/tf_outputs.py, ci/scripts/bundle-deploy.sh) and the Helm values.

output "aks_clusters" {
  description = "Per region: name, resource_group, location, fqdn, oidc_issuer_url."
  value = {
    for k, a in module.aks : k => {
      name            = a.name
      resource_group  = a.resource_group_name
      location        = a.location
      fqdn            = a.fqdn
      oidc_issuer_url = a.oidc_issuer_url
    }
  }
}

output "kong_public_ips" {
  description = "Per region: the static IP and DNS name for Kong's LoadBalancer service (the Front Door origin)."
  value       = { for k, a in module.aks : k => { ip_address = a.kong_ip_address, fqdn = a.kong_fqdn, resource_group = a.resource_group_name } }
}

output "acr_login_server" {
  value = data.azurerm_container_registry.acr.login_server
}

output "key_vault_uri" {
  value = module.data.key_vault_uri
}

output "key_vault_name" {
  description = "Holds Vault's unseal key, root token and recovery key, and the Grafana admin password."
  value       = module.data.key_vault_name
}

output "vault_unseal_key_name" {
  description = "Key Vault key for HashiCorp Vault's azurekeyvault seal."
  value       = module.data.vault_unseal_key_name
}

output "eventhub_namespace_fqdn" {
  value = module.data.eventhub_namespace_fqdn
}

output "sql_fqdn" {
  description = "The failover group listener when enable_sql_failover, else the primary server."
  value       = module.data.sql_fqdn
}

output "sql_database_name" {
  value = module.data.sql_database_name
}

output "storage_account_name" {
  value = module.data.storage_account_name
}

output "databricks_host" {
  value = module.databricks.workspace_url
}

output "databricks_access_connector_id" {
  value = module.databricks.access_connector_id
}

output "databricks_access_connector_client_id" {
  description = "The access connector's identity; db-init makes it a SQL user in pipeline_writer."
  value       = module.databricks.access_connector_client_id
}

output "front_door_id" {
  description = "X-Azure-FDID value Kong requires (P-7)."
  value       = var.front_door_enabled ? module.edge[0].front_door_id : ""
}

output "front_door_endpoint_hostname" {
  value = var.front_door_enabled ? module.edge[0].endpoint_hostname : ""
}

output "workload_identity_client_ids" {
  description = "Service name -> workload identity client ID (Helm services.<name>.workloadIdentityClientId)."
  value       = { for s in var.services : s => module.identity.client_ids[s] }
}

output "vault_identity_client_id" {
  description = "Workload identity of HashiCorp Vault (Key Vault auto-unseal), service account vault/vault."
  value       = module.identity.client_ids["vault"]
}

output "istio_revision" {
  value = var.istio_revision
}

output "environment" {
  value = var.environment
}
