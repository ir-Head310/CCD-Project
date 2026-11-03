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
  # On the MAHE Azure for Students subscription, policy allows only uaenorth, centralindia,
  # koreacentral, indiasouthcentral and malaysiawest, and centralindia offers no usable VM sizes.
  # indiasouthcentral (Hyderabad) has Standard_B2s with a 4 vCPU quota.
  description = "Azure region. Azure for Students only allows some regions; change this if creation is denied by policy."
  type        = string
  default     = "indiasouthcentral"
}

variable "monitoring_location" {
  # Data collection rules aren't offered in indiasouthcentral, and the rule must sit in its
  # workspace's region. The cluster can report to a workspace in another region.
  description = "Region for the Log Analytics workspace and its Container Insights data collection rule."
  type        = string
  default     = "centralindia"
}

variable "node_vm_size" {
  description = "VM size for AKS nodes. Standard_B2s (2 vCPU, 4 GiB) is the cheapest size that runs AKS comfortably."
  type        = string
  default     = "Standard_B2s"
}

variable "node_min_count" {
  # 2 keeps both nodes up so a sale never waits ~2.5 min for a node to boot; set 1 to
  # show the cluster autoscaler adding a node (and to halve VM cost while idle).
  description = "Minimum nodes for the AKS cluster autoscaler."
  type        = number
  default     = 2
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

variable "github_oidc_subject" {
  description = <<-EOT
    Exact OIDC subject GitHub presents, if it differs from repo:<owner>/<repo>:ref:refs/heads/<branch>.
    Newer repos send an ID-qualified form such as repo:owner@123/repo@456:ref:refs/heads/main; the
    failing azure/login step prints the exact value in its AADSTS700213 error.
  EOT
  type        = string
  default     = ""
}

variable "budget_alert_emails" {
  description = "Emails that get budget alerts (50% and 80% of budget_amount spent, 100% forecast). Empty = no budget."
  type        = list(string)
  default     = []
}

variable "budget_amount" {
  description = "Monthly subscription budget in the billing currency (USD on Azure for Students)."
  type        = number
  default     = 10
}
