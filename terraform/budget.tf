# --- Budget alert ---------------------------------------------------------------
# Subscription scope rather than the resource group: AKS puts the VMs, load balancer
# and public IP in its own MC_* node resource group, which a resource-group budget
# would miss. Created only when budget_alert_emails is set.
resource "azurerm_consumption_budget_subscription" "main" {
  count           = length(var.budget_alert_emails) > 0 ? 1 : 0
  name            = "budget-${local.name}"
  subscription_id = "/subscriptions/${var.subscription_id}"
  amount          = var.budget_amount
  time_grain      = "Monthly"

  time_period {
    # Azure requires the first day of a month; ignore_changes stops it moving each apply.
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  notification {
    enabled        = true
    threshold      = 50
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = var.budget_alert_emails
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = var.budget_alert_emails
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = var.budget_alert_emails
  }

  lifecycle {
    ignore_changes = [time_period]
  }
}
