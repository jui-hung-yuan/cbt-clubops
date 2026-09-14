output "core_service_url" {
  description = "The private service, cbt-clubops. Not reachable without an ID token."
  value       = google_cloud_run_v2_service.core.uri
}

output "slack_request_url" {
  description = <<-EOT
    Paste this into the Slack app's slash command Request URL
    (https://api.slack.com/apps -> Slash Commands). Slack pings it when you
    save, so it has to exist first — which is why this is an output rather
    than something Terraform could set for you.
  EOT
  value       = "${google_cloud_run_v2_service.slack.uri}/slack/commands/application-doc"
}

output "image_repository" {
  description = "Where `gcloud builds submit --tag` should push."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "service_accounts" {
  description = "The three identities, for granting anything not managed here."
  value = {
    core_run  = google_service_account.core_run.email
    scheduler = google_service_account.scheduler.email
    slack_run = google_service_account.slack_run.email
  }
}
