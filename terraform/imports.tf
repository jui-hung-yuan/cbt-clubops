# Adopting what already exists in cbt-space.
#
# Most of this configuration describes resources that were built by hand from
# docs/DEPLOY.md before Terraform. Those have to be imported into state, or the
# first `apply` fails with "already exists".
#
# The renamed resources are NOT in this list, on purpose. cbt-clubops and
# cbt-clubops-run do not exist yet — Terraform creates them, they run alongside
# the old cbt-membership-agent and cbt-membership-run until you have verified
# them, and only then do the old two get deleted by hand. That cut-over is in
# README.md, and it is the reason the rename was done before the first apply
# rather than after: no import, no destroy-and-recreate, no gap.
#
# HOW TO USE THIS FILE
#   1. Uncomment the blocks for what actually exists. cbt-pandadoc-api-key may
#      not, if the PandaDoc key was only ever in a local .env.
#   2. `terraform plan`. Read the diff: it shows what would be imported and what
#      would then change. The scheduler job will show a change to its http_target
#      uri and audience — that is correct, it is being pointed at cbt-clubops.
#   3. `terraform apply`, then delete this file.
#
# Import IDs are Google's full resource paths, not the short names.

# --- Secrets ---------------------------------------------------------------
# These five returned 409 "already exists" on the first apply, which is how we
# know they are here. Containers only — the values are untouched by any of this.

import {
  to = google_secret_manager_secret.secrets["cbt-google-oauth-client-id"]
  id = "projects/cbt-space/secrets/cbt-google-oauth-client-id"
}

import {
  to = google_secret_manager_secret.secrets["cbt-google-oauth-client-secret"]
  id = "projects/cbt-space/secrets/cbt-google-oauth-client-secret"
}

import {
  to = google_secret_manager_secret.secrets["cbt-google-oauth-refresh-token"]
  id = "projects/cbt-space/secrets/cbt-google-oauth-refresh-token"
}

import {
  to = google_secret_manager_secret.secrets["cbt-slack-bot-token"]
  id = "projects/cbt-space/secrets/cbt-slack-bot-token"
}

import {
  to = google_secret_manager_secret.secrets["cbt-slack-signing-secret"]
  id = "projects/cbt-space/secrets/cbt-slack-signing-secret"
}

# cbt-pandadoc-api-key is deliberately NOT imported: it did not 409, so it does
# not exist. Terraform creates it empty, and the key goes in by hand afterwards.

# --- The scheduler job -----------------------------------------------------
# It exists and keeps its name. It never got as far as failing on the first
# apply — it depends on the Cloud Run service, which depends on the secrets —
# so import it now rather than discover it on the next run.

import {
  to = google_cloud_scheduler_job.membership_drafts
  id = "projects/cbt-space/locations/europe-west1/jobs/cbt-membership-drafts"
}

# Nothing else needs importing. Enabling an already-enabled API is idempotent,
# and the "images" repository and all three service accounts are new.
