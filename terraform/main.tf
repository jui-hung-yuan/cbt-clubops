# CBT club operations — the whole deployment, minus the secret values.
#
# What this file owns: the APIs, the image repository, three service accounts,
# the secret *containers* and who may read them, two Cloud Run services, and
# the schedule.
#
# What it deliberately does not own: **the secret values**. A
# google_secret_manager_secret_version stores its payload in Terraform state in
# plaintext, so the club's Gmail refresh token, the PandaDoc key and the Slack
# tokens are added by hand with gcloud and are never in state, never in a plan
# output, and never in the repository. Terraform owns the container and the IAM
# binding — the tedious half — and stays ignorant of the value.
#
# Nor the €10 budget: that lives on the billing account, not the project, and
# needs permissions this configuration should not hold.

# --- APIs -----------------------------------------------------------------
# disable_on_destroy = false: tearing down this configuration must not disable
# APIs that something else in the project might be using.

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudscheduler.googleapis.com",
    "secretmanager.googleapis.com",
    "logging.googleapis.com",
    "iam.googleapis.com",
  ])

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# --- Where the image lives -------------------------------------------------

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "images"
  format        = "DOCKER"
  description   = "Container images for CBT club operations."

  depends_on = [google_project_service.apis]
}

# --- Identities ------------------------------------------------------------
# Three, each holding the least it can do its job with. The split is the point:
# the public relay's identity can call the private service and read two Slack
# secrets, and that is all it can do anywhere in the project.

resource "google_service_account" "core_run" {
  project      = var.project_id
  account_id   = "cbt-clubops-run"
  display_name = "cbt-clubops runtime"
  description  = "What the private service runs as. Reads five secrets; can invoke nothing."
}

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = "cbt-clubops-scheduler"
  display_name = "Cloud Scheduler caller"
  description  = "Nothing runs as this. Mints the OIDC token for /jobs/membership-drafts; reads no secret."
}

resource "google_service_account" "slack_run" {
  project      = var.project_id
  account_id   = "cbt-clubops-slack-run"
  display_name = "cbt-clubops-slack runtime"
  description  = "What the public relay runs as. Reads the two Slack secrets and may invoke cbt-clubops. No Google credential."
}

# --- Secrets: the containers, never the values -----------------------------

locals {
  # Which identity may read which secret. Adding a secret here grants nothing
  # by itself; the binding below is what does, and it is explicit per reader.
  secret_readers = {
    "cbt-google-oauth-client-id"     = [google_service_account.core_run.email]
    "cbt-google-oauth-client-secret" = [google_service_account.core_run.email]
    "cbt-google-oauth-refresh-token" = [google_service_account.core_run.email]
    "cbt-pandadoc-api-key"           = [google_service_account.core_run.email]
    # The bot token is the one secret both services need: the private one posts
    # notices with it, the relay asks who is in the admin channel with it.
    "cbt-slack-bot-token" = [
      google_service_account.core_run.email,
      google_service_account.slack_run.email,
    ]
    "cbt-slack-signing-secret" = [google_service_account.slack_run.email]
  }

  # Flattened so each (secret, reader) pair is its own resource, which keeps a
  # revoked reader from looking like a changed secret in the plan.
  secret_bindings = merge([
    for secret, readers in local.secret_readers : {
      for reader in readers : "${secret}:${reader}" => {
        secret = secret
        reader = reader
      }
    }
  ]...)
}

resource "google_secret_manager_secret" "secrets" {
  for_each = local.secret_readers

  project   = var.project_id
  secret_id = each.key

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "readers" {
  for_each = local.secret_bindings

  project   = var.project_id
  secret_id = google_secret_manager_secret.secrets[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.reader}"
}

# --- The private service ---------------------------------------------------
# Holds every credential. Never public: the only IAM bindings granting
# run.invoker on it are the scheduler's and the relay's, further down.

resource "google_cloud_run_v2_service" "core" {
  project             = var.project_id
  name                = "cbt-clubops"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  # Renaming this mints a new URL. Both consumers — the scheduler job's OIDC
  # audience and the relay's CORE_SERVICE_URL — are Terraform references, so
  # they follow automatically. Nothing outside this file holds it, which is why
  # this one was cheap to rename and cbt-clubops-slack's URL is not: that one
  # lives in Slack's slash-command configuration, set by hand.

  template {
    service_account = google_service_account.core_run.email
    timeout         = "600s"

    # Extra CPU while the container boots. Billed only for those few seconds,
    # which is cents a year at this frequency. A revision annotation, not a
    # service one — it describes how this revision starts.
    annotations = {
      "run.googleapis.com/startup-cpu-boost" = "true"
    }

    scaling {
      # Not a cost control. It stops two runs overlapping and racing on the same
      # unmarked sheet rows.
      max_instance_count = 1
    }

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        # Throttled is correct here: this service does all its work inside the
        # request, unlike the relay.
        cpu_idle = true
      }

      # Cloud Run injects K_SERVICE and K_REVISION but not the project id, and
      # without it the Slack failure notice loses its "open the logs" link.
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "SPREADSHEET_ID"
        value = var.spreadsheet_id
      }
      env {
        name  = "SHEET_NAME"
        value = var.sheet_name
      }
      env {
        name  = "PROCESS_ROWS_AFTER"
        value = var.process_rows_after
      }
      env {
        name  = "DATE_ORDER"
        value = "DMY"
      }
      env {
        name  = "TIMEZONE"
        value = "Europe/Berlin"
      }
      env {
        name  = "SLACK_CHANNEL"
        value = var.slack_channel
      }
      env {
        name  = "STANDARD_MONTHLY_FEE"
        value = var.fees.standard_monthly
      }
      env {
        name  = "REDUCED_MONTHLY_FEE"
        value = var.fees.reduced_monthly
      }
      env {
        name  = "APPLICATION_FEE"
        value = var.fees.application
      }
      env {
        name  = "CURRENT_MONTH_CUTOFF_DAY"
        value = var.fees.current_month_cutoff_day
      }
      env {
        name  = "DRY_RUN"
        value = tostring(var.dry_run)
      }

      dynamic "env" {
        for_each = {
          GOOGLE_OAUTH_CLIENT_ID     = "cbt-google-oauth-client-id"
          GOOGLE_OAUTH_CLIENT_SECRET = "cbt-google-oauth-client-secret"
          GOOGLE_OAUTH_REFRESH_TOKEN = "cbt-google-oauth-refresh-token"
          SLACK_BOT_TOKEN            = "cbt-slack-bot-token"
          PANDADOC_API_KEY           = "cbt-pandadoc-api-key"
        }

        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.readers]
}

# --- The public relay ------------------------------------------------------
# Same image, different app. Reachable by anyone, because Slack's servers cannot
# present a Google ID token — which is precisely why the credentials are on the
# other service and this one authenticates callers with an HMAC signature.

resource "google_cloud_run_v2_service" "slack" {
  project             = var.project_id
  name                = "cbt-clubops-slack"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.slack_run.email
    timeout         = "300s"

    # Matters more here than on the private service: this one has three seconds
    # to answer Slack, and a cold start currently spends most of them booting.
    annotations = {
      "run.googleapis.com/startup-cpu-boost" = "true"
    }

    scaling {
      # Purely a cost ceiling on a public URL. Not a rate limit: past three
      # instances requests queue. Scanner traffic dies at the signature check.
      max_instance_count = 3
    }

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        # cpu_idle = false is --no-cpu-throttling, and it is required, not a
        # preference. The route acks Slack within three seconds and creates the
        # document afterwards in a background task; with CPU withdrawn at
        # response time that task freezes and the link never arrives.
        cpu_idle = false
      }

      env {
        name  = "APP_MODULE"
        value = "clubops.slack_web:app"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "SLACK_ADMIN_CHANNEL_ID"
        value = var.slack_admin_channel_id
      }
      env {
        name  = "CORE_SERVICE_URL"
        value = google_cloud_run_v2_service.core.uri
      }

      dynamic "env" {
        for_each = {
          SLACK_BOT_TOKEN      = "cbt-slack-bot-token"
          SLACK_SIGNING_SECRET = "cbt-slack-signing-secret"
        }

        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.secrets[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.readers]
}

# --- Who may call what -----------------------------------------------------

resource "google_cloud_run_v2_service_iam_member" "scheduler_may_invoke" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.core.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

# The binding that replaces handing board members the PandaDoc key.
resource "google_cloud_run_v2_service_iam_member" "relay_may_invoke" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.core.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.slack_run.email}"
}

# The relay, and only the relay, is public. Cloud Run's auth setting is per
# service, which is the entire reason there are two of them.
resource "google_cloud_run_v2_service_iam_member" "relay_is_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.slack.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- The schedule ----------------------------------------------------------

resource "google_cloud_scheduler_job" "membership_drafts" {
  project          = var.project_id
  region           = var.region
  name             = "cbt-membership-drafts"
  description      = "Twice-weekly membership fee email drafts."
  schedule         = "0 23 * * 2,6"
  attempt_deadline = "600s"
  paused           = var.scheduler_paused

  # Cloud Run runs in UTC. Without this the run drifts an hour across DST and the
  # "processed YYYY-MM-DD" marker stamps the wrong day for a 23:00 run.
  time_zone = "Europe/Berlin"

  retry_config {
    # n8n never retried, and duplicate-draft detection is deliberately not
    # implemented: retrying a partial batch would draft twice for every guest
    # already handled. The route returns 200 on row failures for the same reason.
    retry_count = 0
  }

  http_target {
    http_method = "POST"
    uri         = "${google_cloud_run_v2_service.core.uri}/jobs/membership-drafts"

    oidc_token {
      service_account_email = google_service_account.scheduler.email
      # The audience is the service's base URL, with no path. A token minted for
      # the full path is rejected with a 401 that looks exactly like a missing
      # IAM binding.
      audience = google_cloud_run_v2_service.core.uri
    }
  }

  depends_on = [
    google_project_service.apis,
    google_cloud_run_v2_service_iam_member.scheduler_may_invoke,
  ]
}
