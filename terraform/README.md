# Deploying with Terraform

The infrastructure in `docs/DEPLOY.md`, as code. Deploying is two commands
rather than a page of `gcloud`, and — more to the point — what is deployed is
readable in one file instead of reconstructed from shell history.

```bash
gcloud auth application-default login          # once per machine; see below
cd terraform
cp terraform.tfvars.example terraform.tfvars   # then fill it in
terraform init
terraform apply
```

> **`gcloud auth login` is not enough.** That authenticates the `gcloud` CLI.
> Terraform's Google provider uses Application Default Credentials, a separate
> file, and without it every plan fails with *"Attempted to load application
> default credentials … No credentials loaded"*.
>
> ```bash
> gcloud auth application-default login
> gcloud auth application-default set-quota-project cbt-space
> ```
>
> Check which account the browser authorises. If you are signed into another
> Google account in the same browser — a work one, say — it will authorise that
> one, and the result is permission errors that read like a broken configuration
> rather than a wrong identity. The same trap as minting the refresh token in
> `../docs/DEPLOY.md`.

`DEPLOY.md` is still the reference for *why* each setting is what it is, and
for everything Terraform does not do: minting the refresh token, the first-run
procedure, reading the logs, and what to check when a run goes wrong.

---

## What Terraform owns, and what it does not

| | owned here |
|---|---|
| APIs, Artifact Registry | yes |
| The three service accounts | yes |
| Secret *containers* and who may read them | yes |
| Both Cloud Run services | yes |
| The Cloud Scheduler job and its OIDC audience | yes |
| **Secret values** | **no — on purpose** |
| The container image | no — built separately |
| The €10 budget | no |
| The project itself, the OAuth client, the refresh token | no |

**Secret values stay out of Terraform.** A `google_secret_manager_secret_version`
stores its payload in state in plaintext, so putting the club's Gmail refresh
token there would move it from one well-guarded place to a file on a laptop and
a bucket. Terraform creates the empty container and grants the IAM — the tedious,
error-prone half — and never learns the value. You add those by hand, once:

```bash
printf '%s' "<value>" | gcloud secrets versions add cbt-google-oauth-client-id \
  --data-file=- --project cbt-space
```

Do this **before the first apply**. A Cloud Run service referencing a secret
with no versions fails to start, and the error names the secret.

The budget is excluded for a different reason: it lives on the billing account,
not the project, and needs permissions this configuration should not hold.

## Building the image

Terraform deploys an image; it does not build one.

**Run this from the repository root, not from `terraform/`.** The build context
is the current directory, and the Dockerfile is one level up:

```bash
cd ..                      # the repository root, where the Dockerfile is
TAG="europe-west1-docker.pkg.dev/cbt-space/images/clubops:$(date +%Y-%m-%d-%H%M)"
gcloud builds submit --tag "$TAG" --project cbt-space
echo "$TAG"                # paste this into terraform.tfvars
```

### The club's bank details are build arguments

The IBAN, BIC, bank, account owner and the signature on the letter are **not in
this repository** — they are a named person's, and the repository is public. They
are passed at build time, and land in two places at once: drawn into the
application form, and set as environment defaults for the email template. One
build, one source, so the letter and the form cannot disagree about where the
money goes.

`gcloud builds submit --tag` cannot pass build arguments, so the command above
produces a **placeholder image** — a complete, working form and letter that say
`DE00 0000 0000 0000 0000 00` and are signed "The VP Membership". Good for
testing; not for guests. The first run of such an image logs a warning saying so.

To build with the real values, use Docker directly (and this is what CI does):

```bash
docker build -t "$TAG" \
  --build-arg BANK_IBAN="DE.. .... .... .... .... .." \
  --build-arg BANK_BIC="..." \
  --build-arg BANK_NAME="..." \
  --build-arg BANK_OWNER="..." \
  --build-arg SIGNATURE_NAME="..., VP Membership" .
docker push "$TAG"
```

They are not secrets — every guest is given the IBAN — but in GitHub Actions use
**secrets** rather than variables anyway: workflow logs on a public repository
are public, and secrets are masked automatically.

Changing any of them means a rebuild, not just an apply. That is correct rather
than unfortunate: the IBAN is printed on the form, so a treasurer change requires
a new form regardless.

Run from the wrong directory it fails with *"Invalid value for [source]:
Dockerfile required when specifying --tag"*, which names the flag rather than
the actual problem.

`.gcloudignore` at the repository root decides what gets uploaded. It matters
more here than usual: gcloud normally falls back to `.gitignore`, but this
directory is not a git repository, so without that file the upload is 340MB —
`.venv` included, along with a local `.env`. With it, 1.2MB.

Put that tag in `terraform.tfvars` and apply. Both services run the same image —
`APP_MODULE` chooses which app — so one build deploys both and they cannot drift.

A dated tag rather than `:latest` is worth the extra step: it makes "what is
running right now" answerable, and a rollback becomes editing one line back to
the previous tag and applying.

### The first build needs the repository first

`gcloud builds submit` cannot push to a repository that does not exist, and
`image` is a required variable, so the very first time is three steps rather
than two:

```bash
terraform apply -target=google_artifact_registry_repository.images \
  -var image=placeholder                      # the value is unused here
gcloud builds submit --tag "$TAG" --project cbt-space
terraform apply                               # with the real tag in tfvars
```

Only ever needed once.

### The repository you can already see

`cloud-run-source-deploy` in the console is not this one. `gcloud run deploy
--source .` creates it automatically, named after the service, and that is where
the image the current `cbt-clubops` runs was pushed.

It is deliberately not managed here, because **`gcloud run deploy --source .`
and Terraform cannot both own a service.** Each `gcloud run deploy` creates a
revision from its own flags, which the next `terraform apply` would revert. Once
Terraform owns the services, building and deploying are the two separate
commands above.

Delete that repository when you delete `cbt-clubops`, not before — it
holds the image that service is running, and that image is your rollback.

## Names

The services were renamed from `cbt-membership-*` to `cbt-clubops-*` before the
first apply, while renaming was still free. What each name means:

| name | what it is |
|---|---|
| `cbt-clubops` | the private service. Holds every credential, reachable only with an ID token |
| `cbt-clubops-slack` | the public relay. Verifies Slack's signature, checks the channel ACL, calls the above |
| `cbt-clubops-run` | what `cbt-clubops` runs as. Reads five secrets, can invoke nothing |
| `cbt-clubops-slack-run` | what the relay runs as. Reads two Slack secrets, may invoke `cbt-clubops` |
| `cbt-clubops-scheduler` | Cloud Scheduler's identity. Nothing runs as it; it reads no secret |
| `cbt-membership-drafts` | the scheduler job — **deliberately still "membership"** |

That last row is the rule: a name for the *system* is `clubops`, a name for a
*flow* says which flow. The job really is the membership drafts job, and a
Sergeant at Arms job will sit beside it under its own name. The same reasoning
keeps `#cbt-clubops-admin` and every `cbt-google-*` / `cbt-slack-*` secret
as they are.

The service accounts carry no `-sa` suffix because every one of them ends in
`@cbt-space.iam.gserviceaccount.com` and appears only after a `serviceAccount:`
prefix. `-run` means a runtime identity, its absence means a caller.

## The first apply: adopting, and cutting over

**Read this before running `apply` for the first time.** Two different things
are happening, and only one of them is an import.

**Imported**, because it exists and keeps its name: the five secrets, the
scheduler job, the enabled APIs, the image repository. `imports.tf` has a
commented-out block for each. Uncomment what exists, `terraform plan`, and read
the diff — it is telling you where reality and this file disagree, which is the
most useful plan you will ever run here.

**Created fresh**, because it was renamed or is new: `cbt-clubops`,
`cbt-clubops-slack`, and all three service accounts. Terraform makes these
alongside the old `cbt-membership-agent` and `cbt-membership-run`, which it does
not know about and will not touch.

So the first apply leaves you with both, which is the point — you verify the new
one before anything is lost.

### Cutting over

```bash
# 1. Pause the schedule so nothing fires mid-cut-over.
terraform apply -var scheduler_paused=true

# 2. Prove the new private service works, dry, end to end.
terraform apply -var dry_run=true
gcloud scheduler jobs run cbt-membership-drafts \
  --project cbt-space --location europe-west1
#    ...then read the logs for cbt-clubops, not cbt-clubops.

# 3. Point the Slack app at the new relay. `terraform output slack_request_url`
#    prints the value; paste it into the slash command's Request URL, then run
#    /application-doc in the admin channel and confirm the link comes back.

# 4. Real run, schedule back on.
terraform apply    # dry_run and scheduler_paused back to their defaults

# 5. Only now, delete the old estate. Nothing references it any more.
gcloud run services delete cbt-clubops \
  --project cbt-space --region europe-west1
gcloud iam service-accounts delete \
  cbt-membership-run@cbt-space.iam.gserviceaccount.com --project cbt-space
```

Do not skip to step 5. A deleted service account email is unusable for 30 days,
so an early deletion is the one step here with no quick undo.

The old Slack Request URL keeps pointing at a service that no longer exists once
step 5 runs, so step 3 has to happen first — that URL is the single piece of
configuration Terraform cannot reach.

Expect the plan to want to *replace* Cloud Run revisions on later applies. That
is fine; a new revision is how Cloud Run deploys anything.

## Ordinary use, afterwards

| to | do |
|---|---|
| Deploy a code change | build a new tag, update `image`, `terraform apply` |
| Roll back | set `image` to the previous tag, `terraform apply` |
| Change a fee | edit `fees` in `variables.tf`, apply |
| Do a dry run | `terraform apply -var dry_run=true`, run once by hand, then apply again |
| Pause the schedule | `terraform apply -var scheduler_paused=true` |
| Rotate a secret | `gcloud secrets versions add …`, then apply to force new revisions |

That last one has a trap worth knowing: `version = "latest"` is resolved when a
revision *starts*, so adding a secret version changes nothing on a running
service. Something has to create a new revision. `terraform apply` will not do
it on its own if nothing else changed — bump the image tag, or use
`gcloud run services update --update-env-vars ROTATED_AT=$(date +%s)`.

## State

Local by default: one file, `terraform.tfstate`, next to this README, gitignored.
Fine for one maintainer.

**Before a second board member ever runs `apply`**, move state to GCS —
uncomment the backend block in `versions.tf` and follow the comment there. Two
people applying against separate local state files will each try to create
everything, and the second will fail confusingly. State holds no secret values,
but it does hold the full configuration, so the bucket should not be public.

## What has not been verified

`terraform validate` passes. Nothing here has been run against the live project
— no `plan`, no `apply` — so treat the first `plan` output as the real review,
particularly the import step above.
