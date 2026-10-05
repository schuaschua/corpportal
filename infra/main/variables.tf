variable "subscription_id" {
  description = "Subscription; null = ARM_SUBSCRIPTION_ID from Jenkins' environment."
  type        = string
  default     = null
}

# ---------- environment (environments/<env>.tfvars; one state per environment)
variable "environment" {
  description = "dev (one region, Kong's public IP) or prod (Front Door, optional region 2)."
  type        = string
  default     = "prod"
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment: dev or prod."
  }
}

variable "front_door_enabled" {
  description = "Front Door Standard in front of Kong (prod). Off: users reach Kong's public IP over HTTPS (dev)."
  type        = bool
  default     = true
}

# ---------- regions (P-11: variables, so a real rollout can move to UAE North / UAE Central)
variable "primary_region" {
  type    = string
  default = "westus3"
}

variable "secondary_region" {
  type    = string
  default = "northcentralus"
}

# ---------- bootstrap resource groups (created by infra/bootstrap, never here; P-2)
variable "resource_group_primary" {
  type    = string
  default = "rg-corportal-primary"
}

variable "resource_group_secondary" {
  type    = string
  default = "rg-corportal-secondary"
}

variable "resource_group_data" {
  type    = string
  default = "rg-corportal-data"
}

variable "acr_name" {
  type    = string
  default = "exampleacr"
}

variable "acr_resource_group" {
  type    = string
  default = "rg-example-shared"
}

variable "name_suffix" {
  description = "Suffix for globally unique names (storage, Key Vault, SQL, Event Hubs, Front Door)."
  type        = string
  default     = "poc01"
  validation {
    condition     = can(regex("^[a-z0-9]{2,8}$", var.name_suffix))
    error_message = "name_suffix: 2-8 lowercase letters or digits."
  }
}

# ---------- feature flags
variable "secondary_region_enabled" {
  description = "Demo day (Saturday): region 2 network and AKS, plus its Front Door origin."
  type        = bool
  default     = false
}

variable "enable_sql_failover" {
  description = "Failover dry run: upgrades the SQL tier, adds a server in region 2 and a failover group."
  type        = bool
  default     = false
}

# ---------- AKS
variable "jenkins_public_ip" {
  description = "Public IP of the Jenkins VM: the only address the AKS API server (plus extra_authorized_ip_ranges) and the Key Vault firewall accept."
  type        = string
  validation {
    condition     = can(cidrhost("${var.jenkins_public_ip}/32", 0))
    error_message = "jenkins_public_ip must be an IPv4 address."
  }
}

variable "extra_authorized_ip_ranges" {
  description = "More CIDRs allowed to reach the AKS API server (for example the owner's laptop)."
  type        = list(string)
  default     = ["203.0.113.5/32"] # the owner, 2026-10-01
}

variable "aks_admin_group_object_ids" {
  description = "Entra groups that administer the clusters (local accounts are off). Must contain id-corportal-jenkins."
  type        = list(string)
  validation {
    condition     = length(var.aks_admin_group_object_ids) > 0
    error_message = "At least one AKS admin group is required: local accounts are disabled."
  }
}

variable "aks_system_vm_size" {
  type    = string
  default = "Standard_B2s" # the owner: under $0.05/h; 2 vCPU / 4 GiB, westus3 BS family quota 10 vCPU
}

variable "kubernetes_version" {
  description = "AKS version; must suit istio_revision (asm-1-29: 1.31-1.36)."
  type        = string
  default     = "1.35"
}

variable "istio_revision" {
  description = "Managed Istio add-on revision."
  type        = string
  default     = "asm-1-29" # supported in westus3 for k8s 1.31-1.36 (az aks mesh get-revisions)
}

# ---------- data
variable "sql_admin_login" {
  description = "Display name of the SQL Entra admin."
  type        = string
  default     = "corportal-admins"
}

variable "sql_admin_object_id" {
  description = "Entra object ID of the SQL admin; null = the first AKS admin group."
  type        = string
  default     = null
}

# ---------- Databricks
variable "databricks_metastore_id" {
  description = "Unity Catalog metastore to assign to the workspace; empty = rely on automatic assignment."
  type        = string
  default     = ""
}

variable "services" {
  description = "Services that get a workload identity (Kubernetes service account = service name, namespace corportal)."
  type        = list(string)
  default     = ["accounts-api", "payments-api", "insights-api", "outbox-relay", "portal-web"]
}
