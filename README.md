# CBT Club Operations

Back-office automation for the Center Berlin Toastmasters board — the recurring,
mechanical parts of running the club, so an officer's evening is spent on the
club rather than on paperwork.

Membership is the first area covered, and today the only one:

- **Membership fee drafts.** Twice a week, the guest registration sheet is read,
  each new guest's fee worked out, their welcome email drafted in the CBT Gmail
  account, and a note posted to Slack.
- **Application documents.** On demand, a board member runs `/application-doc` in
  Slack and gets a PandaDoc application form, in draft, with every field placed
  and assigned.

**Everything drafts. Nothing sends.** `integrations/gmail.py` has no send code
path, `integrations/pandadoc.py` has none either, and the granted OAuth scopes
are asserted on every run. The `gmail.compose` scope does *not* prevent sending —
Google documents it as "Manage drafts and send emails" — so the guarantee lives
in the code, not the scope. A human reviews and sends, every time.

## How it runs

```
Cloud Scheduler          0 23 * * 2,6  Europe/Berlin
      │ OIDC POST, runs as cbt-clubops-scheduler
      ▼
Cloud Run  cbt-clubops  (--no-allow-unauthenticated)
      │ reads secrets as cbt-clubops-run
      ▼
acts as cb.toastmasters.d95@gmail.com via an OAuth refresh token
      ▼
Sheets  →  fee calculation  →  Gmail draft  →  mark row  →  Slack
```

Cloud Scheduler cannot run code — the only thing it can do when it fires is make
an HTTP request. That is the entire reason there is a web server here.

The second flow is manual, because the gate is whether a guest has paid and wants
to join:

```
/application-doc Ada Lovelace ada@example.com   in #cbt-clubops-admin
      │ signed by Slack, allowed by channel membership
      ▼
Cloud Run  cbt-clubops-slack  (public, holds only Slack's tokens)
      │ ID token, runs as cbt-clubops-slack-run
      ▼
Cloud Run  cbt-clubops  →  PandaDoc draft  →  link back to the channel
```

Two services from one image. Slack's servers cannot present a Google ID token, so
that endpoint cannot be IAM-protected — which is exactly why the credentials live
on the other side of it.

## Layout

```
src/clubops/
  web.py          the private service's routes
  slack_web.py    the public relay's one route
  jobs.py         builds the real Sheets / Gmail / Slack / PandaDoc clients
  pipeline.py     the workflow
  config.py       environment variables, validated at startup
  observability.py
  domain/         fee · timestamps · email_template · slack_messages · models
                  application_form · slack_command
  integrations/   sheets · gmail · slack · pandadoc · google_auth · ports
                  run_invoker
tests/            unit · integration · fixtures
scripts/          operational and build scripts
terraform/        the deployment
docs/             the runbook, Slack setup, background
```

`domain/` is pure: no I/O, no network, no framework. `integrations/` is I/O only,
behind the protocols in `integrations/ports.py`. `pipeline.py` is the one place
they meet — which is why the tests can hand it fakes and verify the whole workflow
with no credentials.

## Local development

```bash
uv sync
uv run pre-commit install   # lint, secret scanning and tests before each commit
cp .env.example .env        # then fill in the secrets
uv run pytest               # 295 tests, no network, no credentials
```

Both flows can be run locally, and both honour `DRY_RUN=true` in `.env` — which
is how to try them safely, since a Gmail draft and a PandaDoc document are both
real objects that then have to be deleted by hand:

```bash
# the membership draft flow
uv run python scripts/run_locally.py

# the pandadoc draft flow
uv run python scripts/create_application_doc.py \
    --name "Ada Lovelace" --email ada@example.com
```

The web server exists only because Cloud Scheduler can do nothing but make an
HTTP request. To exercise the routes rather than the workflow:

```bash
uv run uvicorn clubops.web:app --port 8080         # the private service
uv run uvicorn clubops.slack_web:app --port 8081   # the Slack relay
```

Each serves its own routes locally. What does not work is the hop between them:
the relay authenticates to the private service with an ID token minted from
Cloud Run's metadata server, which does not exist on a laptop, so
`/slack/commands/application-doc` fails after acknowledging Slack. Call
`/jobs/application-document` on port 8080 directly instead.

## Continuous integration

`.github/workflows/ci.yml` runs on every branch and every pull request: ruff and
the test suite, a check that the generated form and field manifest are not stale,
a secret scan over the full history, `terraform fmt` and `validate`, and a Docker
build that asserts an unconfigured image carries placeholder bank details while a
configured one carries the real ones.

It needs **no secrets and no cloud access** — the ports in
`integrations/ports.py` are what make that possible. Deploying is a separate
workflow with a separate trigger.

## Documentation

| | |
|---|---|
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Project setup, both services, the schedule, the first run |
| [`terraform/README.md`](terraform/README.md) | The same deployment as code — the preferred route |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | Running it: calling by hand, failure modes, changing the fees |
| [`docs/SLACK.md`](docs/SLACK.md) | The Slack app, its tokens, and who may run the command |
| [`docs/FORM.md`](docs/FORM.md) | How the PandaDoc application form is built and placed |
| [`docs/BACKGROUND.md`](docs/BACKGROUND.md) | Where this came from, and why a few names are odd |
