# Deploying

Setting up the project, deploying both services, and the first run. What to do
once it is running is in [OPERATIONS.md](OPERATIONS.md); the Slack app is in
[SLACK.md](SLACK.md).

Two Cloud Run services from one image:

| | | |
|---|---|---|
| `cbt-clubops` | private, holds every credential | the two job routes |
| `cbt-clubops-slack` | public, holds only Slack's tokens | the slash command |

`APP_MODULE` chooses which app the container runs, so one build deploys both and
they cannot drift apart.

---

## Two ways to deploy

**`terraform/` is the one to use.** It owns the APIs, Artifact Registry, the
three service accounts, the secret containers and their IAM, both Cloud Run
services and the scheduler job. Build an image, set one variable, apply:

```bash
cd terraform && terraform apply
```

See `terraform/README.md`, and read its "first apply" section before running it
— everything below already exists, so the existing estate has to be imported
into state first or the apply fails on "already exists".

**The `gcloud` commands below are kept anyway**, for three reasons. They are
what actually built this, so they are the record of how the project was set up;
they explain *why* each flag is what it is, which the Terraform comments point
back to; and a few things are not in Terraform at all — minting the refresh
token, the secret *values*, the budget, the first-run procedure, and everything
under "when things go wrong".

Where the two disagree, Terraform is what is deployed.

---

---

## One-time Google Cloud setup

### 1. The project — done

Recorded here so it can be rebuilt, not because you need to run it again.

```bash
export PROJECT_ID=cbt-space          # project IDs must be 6-30 chars; "cbt" is too short
export ORG_ID=<org-id>               # gcloud organizations list
export BILLING_ACCOUNT=<billing-account-id>   # gcloud billing accounts list

gcloud auth login                    # as the account that owns the project
gcloud projects create "$PROJECT_ID" --name="CBT Space" --organization="$ORG_ID"
gcloud billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT"

gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com secretmanager.googleapis.com logging.googleapis.com \
  --project "$PROJECT_ID"
```

**The project ID is immutable** and appears in every service account email
(`cbt-clubops-run@cbt-space.iam.gserviceaccount.com`), so it cannot be
renamed later without recreating everything.

Every command below passes `--project "$PROJECT_ID"` explicitly rather than
running `gcloud config set project`. Your gcloud default is a work project
(`pangea-foundation-model`); changing it globally would silently redirect
unrelated commands.

**Spending.** A €10/month budget with alerts at 50/90/100% is in place:

```bash
gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" \
  --display-name="cbt-space monthly cap" --budget-amount=10EUR \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0 \
  --filter-projects="projects/$PROJECT_ID" \
  --billing-project="$PROJECT_ID"
```

`--billing-project` is required: without it the call is charged against your
gcloud default project and fails with `USER_PROJECT_DENIED`.

> A budget **alerts, it does not cap.** The n8n setup had no billing account at
> all, which made a surprise charge structurally impossible; this is weaker. If
> a runaway bill matters more than uptime, add a Cloud Function on the budget
> Pub/Sub topic that unlinks billing at 100%.

**Sheets and Gmail are not enabled here.** With OAuth *user* credentials, API
enablement and quota are attributed to the project that owns the OAuth client —
the CBT account's project, where both are already on.

### 2. The refresh token

The club mailbox is a consumer Gmail account, so a service account is not an
option: domain-wide delegation needs Google Workspace. The service authenticates
as a user.

1. In the CBT account's Cloud project, open the existing OAuth client (the same
   one n8n uses) and add `http://localhost:8765/` to its **Authorised redirect
   URIs**. Additive — leave the n8n callback in place.
2. Mint the token, signing in as `cb.toastmasters.d95@gmail.com`:

```bash
export GOOGLE_OAUTH_CLIENT_ID=...
export GOOGLE_OAUTH_CLIENT_SECRET=...
uv run python scripts/mint_refresh_token.py
```

The script prints the account and scopes it actually got. Check the account —
if you are signed into a personal account in the same browser, Google will
authorise that one and everything will appear to work until the club needs
access.

### 3. Secrets

```bash
for name in cbt-google-oauth-client-id cbt-google-oauth-client-secret \
            cbt-google-oauth-refresh-token cbt-slack-bot-token; do
  gcloud secrets create "$name" --replication-policy=automatic --project "$PROJECT_ID"
done
# then, for each, without leaving the value in shell history:
printf '%s' "<value>" | gcloud secrets versions add cbt-google-oauth-client-id \
  --data-file=- --project "$PROJECT_ID"
```

### 4. Service accounts

Both accounts already exist. Only the secret bindings remain, and they must wait
until the secrets themselves are created (step 3).

```bash
# Already created:
#   cbt-clubops-run@cbt-space.iam.gserviceaccount.com     (Cloud Run runtime)
#   cbt-clubops-scheduler@cbt-space.iam.gserviceaccount.com  (Cloud Scheduler OIDC)

for name in cbt-google-oauth-client-id cbt-google-oauth-client-secret \
            cbt-google-oauth-refresh-token cbt-slack-bot-token; do
  gcloud secrets add-iam-policy-binding "$name" \
    --member="serviceAccount:cbt-clubops-run@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor \
    --project "$PROJECT_ID"
done
```

---

---

## Deploy

```bash
gcloud run deploy cbt-clubops \
  --project "$PROJECT_ID" --source . --region europe-west1 \
  --no-allow-unauthenticated \
  --service-account cbt-clubops-run@cbt-space.iam.gserviceaccount.com \
  --max-instances 1 --timeout 600 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=cbt-space,SPREADSHEET_ID=<spreadsheet-id>,SHEET_NAME=Form responses 1,PROCESS_ROWS_AFTER=2026-08-12,DATE_ORDER=DMY,TIMEZONE=Europe/Berlin,SLACK_CHANNEL=#cbt-clubops-admin,STANDARD_MONTHLY_FEE=21,REDUCED_MONTHLY_FEE=14.5,APPLICATION_FEE=25,CURRENT_MONTH_CUTOFF_DAY=10,DRY_RUN=false" \
  --set-secrets "GOOGLE_OAUTH_CLIENT_ID=cbt-google-oauth-client-id:latest,GOOGLE_OAUTH_CLIENT_SECRET=cbt-google-oauth-client-secret:latest,GOOGLE_OAUTH_REFRESH_TOKEN=cbt-google-oauth-refresh-token:latest,SLACK_BOT_TOKEN=cbt-slack-bot-token:latest"
```

`--max-instances 1` is not a cost control. It prevents two runs overlapping and
racing on the same unmarked rows.

`GOOGLE_CLOUD_PROJECT` has to be passed explicitly. Cloud Run injects `K_SERVICE`,
`K_REVISION` and `K_CONFIGURATION`, but not the project id — without it the Slack
failure message loses its "open the logs" link.

Grant the scheduler service account permission to invoke it:

```bash
gcloud run services add-iam-policy-binding cbt-clubops \
  --project "$PROJECT_ID" --region europe-west1 --role roles/run.invoker \
  --member "serviceAccount:cbt-clubops-scheduler@cbt-space.iam.gserviceaccount.com"
```

## Schedule

```bash
URL=$(gcloud run services describe cbt-clubops \
        --project "$PROJECT_ID" --region europe-west1 --format="value(status.url)")

gcloud scheduler jobs create http cbt-membership-drafts \
  --project "$PROJECT_ID" --location europe-west1 \
  --schedule "0 23 * * 2,6" --time-zone "Europe/Berlin" \
  --uri "${URL}/jobs/membership-drafts" --http-method POST \
  --oidc-service-account-email cbt-clubops-scheduler@cbt-space.iam.gserviceaccount.com \
  --oidc-token-audience "${URL}" \
  --attempt-deadline 600s --max-retry-attempts 0
```

Two settings carry real weight:

- **`--time-zone "Europe/Berlin"`.** Cloud Run runs in UTC. Without this the run
  drifts by one or two hours across DST, and the `processed YYYY-MM-DD` marker
  would stamp the wrong day for a 23:00 run. (The marker itself is computed with
  `ZoneInfo("Europe/Berlin")` in `pipeline.processed_marker`.)
- **`--max-retry-attempts 0`.** n8n never retried. Since duplicate-draft
  detection is deliberately *not* implemented, retrying a partially-completed
  batch would create a second draft for every guest already handled.

Correspondingly, `/jobs/membership-drafts` returns **200 even when rows failed**,
with a JSON summary. Failures reach you through Slack, not the HTTP status. A 5xx
means the run died before any row was touched — bad config, or an unreadable
sheet.

---

---

## The Slack relay (`cbt-clubops-slack`)

A second Cloud Run service, from the **same image**, whose only job is to receive
`/application-doc` from Slack and pass it to the private service. It exists
because Slack's servers cannot present a Google ID token, so its endpoint cannot
be IAM-protected — and everything reachable from a public URL is therefore kept
away from the credentials.

```
Slack  ──signature──▶  cbt-clubops-slack   ──ID token──▶  cbt-clubops
                       public                                 --no-allow-unauthenticated
                       holds: signing secret                   holds: Gmail refresh token,
                              bot token                               PandaDoc key
```

If the relay is ever compromised, what is on it is a Slack signing secret. Not
the club's mailbox. That is the whole reason for the second deploy, and
`tests/unit/test_boundaries.py` enforces it: `slack_web.py` may not import
`jobs`, `pipeline`, `gmail`, `sheets`, `pandadoc` or `google_auth`, and
`load_relay_settings` may not read any of the private service's variables.

Slack app setup — the bot token, the signing secret, the slash command, who is
allowed to run it — is in **`docs/SLACK.md`**. Do that first; you need the
signing secret before the deploy below, and the deploy's URL before the slash
command.

### Service account and permissions

A third account, so the relay's identity is distinct from the one holding the
Google OAuth secrets:

```bash
export PROJECT_ID=cbt-space

gcloud iam service-accounts create cbt-clubops-slack-run \
  --display-name="Slack relay (public)" --project "$PROJECT_ID"

# It reads exactly two secrets, and neither can create anything on its own.
for name in cbt-slack-bot-token cbt-slack-signing-secret; do
  gcloud secrets add-iam-policy-binding "$name" \
    --member="serviceAccount:cbt-clubops-slack-run@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor --project "$PROJECT_ID"
done

# ...and it may call the private service. This is the binding that replaces
# handing board members the PandaDoc key.
gcloud run services add-iam-policy-binding cbt-clubops \
  --project "$PROJECT_ID" --region europe-west1 --role roles/run.invoker \
  --member "serviceAccount:cbt-clubops-slack-run@${PROJECT_ID}.iam.gserviceaccount.com"
```

### Deploy

```bash
PRIVATE_URL=$(gcloud run services describe cbt-clubops \
        --project "$PROJECT_ID" --region europe-west1 --format="value(status.url)")

gcloud run deploy cbt-clubops-slack \
  --project "$PROJECT_ID" --source . --region europe-west1 \
  --allow-unauthenticated \
  --service-account cbt-clubops-slack-run@cbt-space.iam.gserviceaccount.com \
  --max-instances 3 --timeout 300 --no-cpu-throttling \
  --set-env-vars "APP_MODULE=clubops.slack_web:app,GOOGLE_CLOUD_PROJECT=cbt-space,SLACK_ADMIN_CHANNEL_ID=C0123456789,CORE_SERVICE_URL=${PRIVATE_URL}" \
  --set-secrets "SLACK_BOT_TOKEN=cbt-slack-bot-token:latest,SLACK_SIGNING_SECRET=cbt-slack-signing-secret:latest"
```

Four flags carry weight here:

- **`--allow-unauthenticated`.** Unavoidable, and the reason this is a separate
  service: Cloud Run's auth setting is per *service*, not per route. Putting the
  Slack route on `cbt-clubops` would have made
  `/jobs/membership-drafts` publicly reachable too.
- **`APP_MODULE=clubops.slack_web:app`.** Same image, different app. The
  Dockerfile defaults to `clubops.web:app`, so the private service needs no
  change and the two can never drift at build time.
- **`--no-cpu-throttling`.** The route acks Slack within three seconds and
  creates the document afterwards, in a background task. Cloud Run withdraws CPU
  the instant a response completes unless told otherwise, which would leave that
  task frozen until some later request happened to wake the instance. The symptom
  is the ack appearing and the link never following.
- **`--max-instances 3`.** Purely a cost ceiling on a public URL. Not a rate
  limit and nothing to do with any one caller: past three instances requests
  queue. Three is far more than a handful of commands a week needs.

`SLACK_ADMIN_CHANNEL_ID` is an **id**, not `#cbt-clubops-admin`. See
`docs/SLACK.md` §3 for where to find it.

### Finish the wiring, then check it

```bash
gcloud run services describe cbt-clubops-slack \
  --project "$PROJECT_ID" --region europe-west1 --format="value(status.url)"
```

Put `<that URL>/slack/commands/application-doc` into the slash command's Request
URL (`docs/SLACK.md` §3). Slack pings it on save, so the deploy has to come
first.

Then, in `#cbt-clubops-admin`:

```
/application-doc Test Guest test@example.com
```

Expect an ephemeral "Creating the application document for Test Guest…" within a
second, then an in-channel message with the link. **Set `DRY_RUN=true` on the
private service for the first attempt** — a created PandaDoc document is real
and has to be deleted by hand; a dry run answers with "DRY_RUN is on, so nothing
was created" and proves the whole chain anyway: signature, membership lookup,
ID token, IAM binding, deferred reply.

Worth trying deliberately once, because each proves a different guard:

- the same command from someone not in the channel — refused by name
- `curl -X POST <relay URL>/slack/commands/application-doc` — `401`, empty body
- `/application-doc Ada Lovelace` — a usage hint, no document

---

---

## First run

Do not let the schedule fire first. Run it by hand twice — once dry, once real —
so a broken credential is discovered with nothing to clean up.

**`gcloud scheduler jobs run` requires the job to be ENABLED**; it fails on a
paused job with `Job.state must be ENABLED for RunJob`. So resume, fire, re-pause:

```bash
export PROJECT_ID=cbt-space
run_once () {
  gcloud scheduler jobs resume cbt-membership-drafts --project "$PROJECT_ID" --location europe-west1
  gcloud scheduler jobs run    cbt-membership-drafts --project "$PROJECT_ID" --location europe-west1
  gcloud scheduler jobs pause  cbt-membership-drafts --project "$PROJECT_ID" --location europe-west1
}

# 1. Dry: exercises scheduler OIDC -> Cloud Run -> secrets -> OAuth -> sheet read
#    -> fee calculation -> rendering, and touches nothing.
gcloud run services update cbt-clubops --project "$PROJECT_ID" \
  --region europe-west1 --update-env-vars DRY_RUN=true
run_once

# 2. Real.
gcloud run services update cbt-clubops --project "$PROJECT_ID" \
  --region europe-west1 --update-env-vars DRY_RUN=false
run_once
```

Read the outcome in the logs — the run summary is not visible anywhere else,
since Cloud Scheduler does not record the response body:

```bash
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="cbt-clubops"' \
  --project "$PROJECT_ID" --limit 100 --freshness=10m \
  --format="value(jsonPayload.message,textPayload)" \
  | grep -iE "run finished|created draft|marked row|posted to|read [0-9]+ rows"
```

Running it a second time is a worthwhile check in itself: it should report
`processed: 0` and create no duplicate draft.

Check, in order: the Gmail drafts folder, the `Draft Status` column, and
`#cbt-clubops-admin`. Then:

```bash
gcloud scheduler jobs resume cbt-membership-drafts --project "$PROJECT_ID" --location europe-west1
```

Leave the n8n workflow inactive (it already is) until one *scheduled* run has
succeeded.
