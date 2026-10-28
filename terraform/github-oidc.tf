# Identity that GitHub Actions logs in as, using OIDC federation (no client secret
# stored in GitHub). Created only when var.github_repo is set.

locals {
  create_ci = var.github_repo != ""
}

data "azuread_client_config" "current" {}

resource "azuread_application" "ci" {
  count        = local.create_ci ? 1 : 0
  display_name = "gh-${local.name}-deployer"
  owners       = [data.azuread_client_config.current.object_id]
}

resource "azuread_service_principal" "ci" {
  count     = local.create_ci ? 1 : 0
  client_id = azuread_application.ci[0].client_id
  owners    = [data.azuread_client_config.current.object_id]
}

resource "azuread_application_federated_identity_credential" "ci" {
  count          = local.create_ci ? 1 : 0
  application_id = azuread_application.ci[0].id
  display_name   = "github-${var.github_branch}"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repo}:ref:refs/heads/${var.github_branch}"
}

# Least privilege: push images, and fetch cluster credentials. Nothing else.
resource "azurerm_role_assignment" "ci_acr_push" {
  count                = local.create_ci ? 1 : 0
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = azuread_service_principal.ci[0].object_id
}

resource "azurerm_role_assignment" "ci_aks_user" {
  count                = local.create_ci ? 1 : 0
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service Cluster User Role"
  principal_id         = azuread_service_principal.ci[0].object_id
}
