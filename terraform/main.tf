resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  name = "${var.project}-${random_string.suffix.result}"
  tags = {
    project = var.project
    purpose = "flash-sale-autoscaling-demo"
  }
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = local.tags
}

# --- Container registry (AWS ECR equivalent) ---------------------------------
resource "azurerm_container_registry" "main" {
  name                = replace("acr${local.name}", "-", "") # alphanumeric, globally unique
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

# --- Monitoring & logging (AWS CloudWatch equivalent) ------------------------
resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${local.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days
  daily_quota_gb      = 1 # hard cap on ingestion so a runaway log loop can't burn credit
  tags                = local.tags
}

# --- Managed Kubernetes (AWS EKS equivalent) ---------------------------------
resource "azurerm_kubernetes_cluster" "main" {
  name                = "aks-${local.name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  dns_prefix          = local.name
  sku_tier            = "Free" # no control-plane charge (EKS bills $0.10/h for this)
  tags                = local.tags

  default_node_pool {
    name                 = "system"
    vm_size              = var.node_vm_size
    auto_scaling_enabled = true # cluster autoscaler adds nodes when HPA pods can't fit
    min_count            = var.node_min_count
    max_count            = var.node_max_count
    os_disk_size_gb      = 30
    upgrade_settings {
      max_surge = "10%"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    load_balancer_sku   = "standard"
  }

  # Container Insights: node/pod CPU & memory metrics plus container stdout logs.
  oms_agent {
    log_analytics_workspace_id      = azurerm_log_analytics_workspace.main.id
    msi_auth_for_monitoring_enabled = true
  }

  lifecycle {
    ignore_changes = [default_node_pool[0].node_count]
  }
}

# Let the cluster's kubelet pull images from ACR without stored credentials.
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                            = azurerm_container_registry.main.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_kubernetes_cluster.main.kubelet_identity[0].object_id
  skip_service_principal_aad_check = true
}
