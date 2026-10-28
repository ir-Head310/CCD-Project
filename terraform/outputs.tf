output "resource_group" {
  value = azurerm_resource_group.main.name
}

output "aks_name" {
  value = azurerm_kubernetes_cluster.main.name
}

output "acr_name" {
  value = azurerm_container_registry.main.name
}

output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "log_analytics_workspace" {
  value = azurerm_log_analytics_workspace.main.name
}

output "get_credentials_command" {
  value = "az aks get-credentials --resource-group ${azurerm_resource_group.main.name} --name ${azurerm_kubernetes_cluster.main.name} --overwrite-existing"
}

# Values to paste into GitHub -> Settings -> Secrets and variables -> Actions -> Variables.
output "github_actions_variables" {
  value = local.create_ci ? {
    AZURE_CLIENT_ID       = azuread_application.ci[0].client_id
    AZURE_TENANT_ID       = data.azuread_client_config.current.tenant_id
    AZURE_SUBSCRIPTION_ID = var.subscription_id
    ACR_NAME              = azurerm_container_registry.main.name
    AKS_RESOURCE_GROUP    = azurerm_resource_group.main.name
    AKS_NAME              = azurerm_kubernetes_cluster.main.name
  } : null
}
