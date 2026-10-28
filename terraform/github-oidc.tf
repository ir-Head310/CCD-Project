# Identity that GitHub Actions logs in as, using OIDC federation (no client secret
# stored in GitHub). Created only when var.github_repo is set.
#
# This uses a user-assigned managed identity rather than an Entra app registration:
# the university tenant does not let students register apps, but a managed identity
# is an ordinary Azure resource that the subscription Owner can create.

locals {
  create_ci = var.github_repo != ""
}

data "azurerm_client_config" "current" {}

resource "azurerm_user_assigned_identity" "ci" {
  count               = local.create_ci ? 1 : 0
  name                = "id-${local.name}-github"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "ci" {
  count               = local.create_ci ? 1 : 0
  name                = "github-${var.github_branch}"
  resource_group_name = azurerm_resource_group.main.name
  parent_id           = azurerm_user_assigned_identity.ci[0].id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = "repo:${var.github_repo}:ref:refs/heads/${var.github_branch}"
}

# Least privilege: push images, and fetch cluster credentials. Nothing else.
resource "azurerm_role_assignment" "ci_acr_push" {
  count                            = local.create_ci ? 1 : 0
  scope                            = azurerm_container_registry.main.id
  role_definition_name             = "AcrPush"
  principal_id                     = azurerm_user_assigned_identity.ci[0].principal_id
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "ci_aks_user" {
  count                            = local.create_ci ? 1 : 0
  scope                            = azurerm_kubernetes_cluster.main.id
  role_definition_name             = "Azure Kubernetes Service Cluster User Role"
  principal_id                     = azurerm_user_assigned_identity.ci[0].principal_id
  skip_service_principal_aad_check = true
}
