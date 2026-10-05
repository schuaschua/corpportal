output "jenkins_identity_id" {
  value = azurerm_user_assigned_identity.jenkins.id
}

output "jenkins_client_id" {
  value = azurerm_user_assigned_identity.jenkins.client_id
}

# Paste into Jenkins as environment for every Terraform stage.
output "jenkins_env" {
  value = <<-EOT
    ARM_USE_MSI=true
    ARM_CLIENT_ID=${azurerm_user_assigned_identity.jenkins.client_id}
    ARM_SUBSCRIPTION_ID=${var.subscription_id}
    ARM_TENANT_ID=${azurerm_user_assigned_identity.jenkins.tenant_id}
  EOT
}

output "backend_config" {
  value = <<-EOT
    resource_group_name  = "${var.tfstate_resource_group}"
    storage_account_name = "${var.tfstate_account}"
    container_name       = "corportal"
    key                  = "main.tfstate"
    use_azuread_auth     = true
    use_msi              = true
  EOT
}
