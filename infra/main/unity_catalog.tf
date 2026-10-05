# Unity Catalog objects the bundle (databricks/databricks.yml) expects: the catalog `corportal`
# on the lake container, and the service credentials its jobs use (sc-portal-eventhubs: the
# Kafka read; sc-portal-sql: the SQL token of pipeline_writer). All of them run as the access
# connector's user-assigned identity (Storage Blob Data Contributor, Event Hubs Data Receiver).
# The lake storage stays private (P-5), so Unity Catalog's control plane can't reach it:
# validation is skipped, and the VNet-injected job clusters use the dfs private endpoint.
# force_destroy: everything goes on Sunday (P-9), including the bundle's schemas and tables.

locals {
  lake_url = "abfss://lake@${module.data.storage_account_name}.dfs.core.windows.net/"
  service_credentials = {
    eventhubs = "sc-portal-eventhubs"
    sql       = "sc-portal-sql"
  }
}

resource "databricks_storage_credential" "lake" {
  name            = "corportal-lake"
  comment         = "Lake container (access connector identity)."
  skip_validation = true
  force_destroy   = true

  azure_managed_identity {
    access_connector_id = module.databricks.access_connector_id
    managed_identity_id = module.databricks.access_connector_identity_id
  }

  # Destroyed before the workspace and connector, not in parallel with them.
  depends_on = [module.databricks]
}

resource "databricks_external_location" "lake" {
  name            = "corportal-lake"
  url             = local.lake_url
  credential_name = databricks_storage_credential.lake.name
  skip_validation = true
  force_destroy   = true
}

resource "databricks_catalog" "corportal" {
  name          = "corportal"
  comment       = "Bronze, silver, gold and ml schemas (the bundle creates them)."
  storage_root  = "${local.lake_url}catalog"
  force_destroy = true

  depends_on = [databricks_external_location.lake]
}

resource "databricks_credential" "service" {
  for_each = local.service_credentials

  name            = each.value
  purpose         = "SERVICE"
  comment         = "corportal ${each.key} (access connector identity)."
  skip_validation = true
  force_destroy   = true

  azure_managed_identity {
    access_connector_id = module.databricks.access_connector_id
    managed_identity_id = module.databricks.access_connector_identity_id
  }

  depends_on = [module.databricks]
}
