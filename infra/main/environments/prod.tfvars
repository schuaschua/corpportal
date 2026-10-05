# prod: the demo. Front Door Standard in front of Kong; region 2 with REGION_SECONDARY_ENABLED.
environment              = "prod"
name_suffix              = "poc01"
primary_region           = "westus3"
secondary_region         = "northcentralus"
resource_group_primary   = "rg-corportal-primary"
resource_group_secondary = "rg-corportal-secondary"
resource_group_data      = "rg-corportal-data"
front_door_enabled       = true
