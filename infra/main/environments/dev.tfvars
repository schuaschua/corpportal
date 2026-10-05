# dev: one region (westus2, its own quota so it can run next to prod), no Front Door; users reach
# Kong's public IP over HTTPS (Let's Encrypt via cert-manager). Never region 2.
environment            = "dev"
name_suffix            = "poc01d"
primary_region         = "westus2"
resource_group_primary = "rg-corportal-dev-primary"
# No region-2 group in dev: the (unused) secondary reference points at the primary one.
resource_group_secondary = "rg-corportal-dev-primary"
resource_group_data      = "rg-corportal-dev-data"
front_door_enabled       = false
