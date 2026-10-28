variable "subscription_id" {
  description = "Azure subscription ID (az account show --query id -o tsv)."
  type        = string
}

variable "project" {
  description = "Short name used as a prefix for resource names."
  type        = string
  default     = "flashsale"
}

variable "location" {
  description = "Azure region. Azure for Students only allows some regions; change this if creation is denied by policy."
  type        = string
  default     = "centralindia"
}

variable "node_vm_size" {
  description = "VM size for AKS nodes. Standard_B2s (2 vCPU, 4 GiB) is the cheapest size that runs AKS comfortably."
  type        = string
  default     = "Standard_B2s"
}

variable "node_min_count" {
  description = "Minimum nodes for the AKS cluster autoscaler."
  type        = number
  default     = 1
}

variable "node_max_count" {
  description = "Maximum nodes for the AKS cluster autoscaler. Student subscriptions usually cap regional vCPUs, so 2 x B2s = 4 vCPU is a safe max."
  type        = number
  default     = 2
}

variable "log_retention_days" {
  description = "Log Analytics retention (30 is the minimum and is included at no extra retention charge)."
  type        = number
  default     = 30
}

variable "github_repo" {
  description = "GitHub repo as owner/name allowed to deploy via OIDC (e.g. aryan/flash-sale-autoscaling). Leave empty to skip creating the CI identity."
  type        = string
  default     = ""
}

variable "github_branch" {
  description = "Branch whose workflow runs may deploy."
  type        = string
  default     = "main"
}
