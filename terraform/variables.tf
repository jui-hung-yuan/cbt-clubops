variable "project_id" {
  description = "The Google Cloud project. Immutable — it appears in every service account email."
  type        = string
  default     = "cbt-space"
}

variable "region" {
  description = "One region for everything: Cloud Run, Cloud Scheduler, Artifact Registry."
  type        = string
  default     = "europe-west1"
}

variable "image" {
  description = <<-EOT
    The container image both services run, fully qualified with a digest or tag.
    Terraform does not build it; see terraform/README.md for the one build
    command. Deploying is then a matter of changing this value and applying,
    which is also how a rollback works.
  EOT
  type        = string
}

variable "spreadsheet_id" {
  description = "The guest registration sheet."
  type        = string
  # No default: the sheet is the club's, and a public repository is not the
  # place for its id. Set it in terraform.tfvars, which is gitignored.
}

variable "sheet_name" {
  type    = string
  default = "Form responses 1"
}

variable "process_rows_after" {
  description = "Registrations before this date are ignored. The n8n go-live date."
  type        = string
  default     = "2026-08-12"
}

variable "slack_channel" {
  description = "Where notices are posted. A #name — chat.postMessage resolves those."
  type        = string
  default     = "#cbt-clubops-admin"
}

variable "slack_admin_channel_id" {
  description = <<-EOT
    The same channel, as an id (C0123456789). Not interchangeable with the
    name above: conversations.members takes only ids, and this one doubles as
    the access-control list for the slash command — whoever is in this channel
    may run it. See docs/SLACK.md.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[CG][A-Z0-9]+$", var.slack_admin_channel_id))
    error_message = "Must be a Slack channel id like C0123456789, not a #name."
  }
}

variable "fees" {
  description = "Rates, deliberately configuration rather than code. Source: docs/CBT_application_form_2026_fees_v2.pdf."
  type = object({
    standard_monthly         = string
    reduced_monthly          = string
    application              = string
    current_month_cutoff_day = string
  })
  default = {
    standard_monthly         = "21"
    reduced_monthly          = "14.5"
    application              = "25"
    current_month_cutoff_day = "10"
  }
}

variable "dry_run" {
  description = <<-EOT
    true = compute and log, but create no draft, write no cell, post no message.
    Set true for the first run against a new deployment, then apply again.
  EOT
  type        = bool
  default     = false
}

variable "scheduler_paused" {
  description = "Leave the twice-weekly job paused until one manual run has succeeded."
  type        = bool
  default     = false
}
