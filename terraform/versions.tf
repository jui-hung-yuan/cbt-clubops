terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # State lives on this machine by default, which is enough for one maintainer
  # and nothing to set up. Before a second board member ever runs `apply`,
  # uncomment this and create the bucket — two people applying against separate
  # local state files will fight over every resource.
  #
  #   gcloud storage buckets create gs://cbt-space-tfstate \
  #     --project cbt-space --location europe-west1 \
  #     --uniform-bucket-level-access
  #   gcloud storage buckets update gs://cbt-space-tfstate --versioning
  #
  # backend "gcs" {
  #   bucket = "cbt-space-tfstate"
  #   prefix = "cbt"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
