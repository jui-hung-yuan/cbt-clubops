# CBT club operations — working notes

Back-office automation for the Center Berlin Toastmasters board. Membership
paperwork is what it does today; the intent is wider — the recurring, mechanical
parts of running the club, for whichever officer owns them. A Sergeant at Arms
flow is the likely second one.

**Everything here drafts and nothing sends.** Not a coincidence of the current
scope: a human reviews every outbound artefact, and the guarantees that make
that true are in the code, not in a scope or a config flag.

Today, two flows:

- Twice a week, Cloud Scheduler calls the service. It reads the guest
  registration sheet, calculates each new guest's membership fee, drafts their
  welcome email in the CBT Gmail account, marks the sheet row, and posts to
  Slack. Ported from an n8n workflow kept outside this repository — its Code
  nodes carry the club's bank details — which is the backup and also the
  source for regenerating the fidelity fixture.
- On demand, a board member runs `/application-doc` in Slack and gets a PandaDoc
  application document, in draft, to review and send.

**The package is `clubops`, and it is flat.** Everything in it today is
membership work, but the name is the repository's scope rather than that flow's,
because renaming a package after it is public is churn nobody enjoys reading in
a history. When a second area lands — a Sergeant at Arms flow is the likely one
— the question to answer is whether `pipeline.py`, `jobs.py` and `web.py` move
down into `clubops/membership/` beside a sibling. Do not pre-build that nesting.

The deployed names moved at the same time: the Cloud Run services are `cbt-clubops` and
`cbt-clubops-slack`, renamed before the first `terraform apply` while renaming
was still free. What kept its name is anything describing a **flow** rather than
the system — the scheduler job `cbt-membership-drafts`, the Slack channel
`#cbt-clubops-admin` — because those really are about membership and a
Sergeant at Arms flow will sit beside them under its own name.

## Layout

```
src/clubops/
  web.py          private service: GET /healthcheck,
                  POST /jobs/membership-drafts, POST /jobs/application-document
  slack_web.py    public relay: POST /slack/commands/application-doc
  jobs.py         builds the real Sheets / Gmail / Slack / PandaDoc clients
  pipeline.py     the workflow
  config.py       env vars, validated at startup; load_settings (private) and
                  load_relay_settings (public) are deliberately separate
  domain/         fee · timestamps · email_template · models
                  slack_messages (both flows' wording, n8n-pinned for the email)
                  application_form · application_fields (generated)
                  slack_command (signature + slash-command parsing)
  integrations/   sheets · gmail · slack · pandadoc · google_auth · ports
                  run_invoker (relay -> private service, with an ID token)
  assets/         the club's form with its bank column emptied, and the
                  tagged PDF generated from it (both checked in)
```

Two flows, only the first on a schedule:

- **membership drafts** — twice a week, sheet → fee → Gmail draft → Slack.
- **application documents** — by hand, name + email → PandaDoc draft. Triggered
  when a guest has paid and wants to join, which is a judgement the service is
  not asked to make. Board members reach it through `/application-doc` in Slack.

Two Cloud Run services, one image, chosen by `APP_MODULE`:
`cbt-clubops` (private, holds every credential) and
`cbt-clubops-slack` (public, holds only Slack's signing and bot tokens).

Deploy and first run: `docs/DEPLOY.md`. Operating it: `docs/OPERATIONS.md`.
The Slack app, its tokens and who may run the command: `docs/SLACK.md`.

## Rules that are load-bearing

- **`domain/` stays pure.** No I/O, no network, no HTTP framework. Enforced by
  `tests/unit/test_boundaries.py`, not by convention.
- **The draft is created before the row is marked.** `mark_processed` requires
  the `draft_id`, so the order cannot be reversed by accident. A failed sheet
  write means the guest is retried next run; the cost is a possible duplicate
  draft, which is visible and deletable. A lost guest is not.
- **The job route returns 200 even when rows fail.** Cloud Scheduler retries on
  non-2xx, and retrying a partial batch would duplicate drafts. Failures go to
  Slack.
- **`integrations/gmail.py` has no send code path**, and `google_auth`
  asserts the granted scopes every run. The `gmail.compose` scope does *not*
  prevent sending — Google documents it as "Manage drafts and send emails" — so
  the guarantee lives in the code.
- **`integrations/pandadoc.py` has no send code path either.** Same rule as
  Gmail, same reason: the API key carries full send permission, so the guarantee
  lives in the code. Asserted over the parsed AST, not by grepping text.
- **The application form's field placement lives in this repo, not PandaDoc.**
  PandaDoc has no coordinate-placement API, and its "create template from file
  upload" endpoint supports neither form fields nor field tags — so a stored
  template cannot carry the placement. `scripts/build_form_fields.py` writes
  PandaDoc **field tags** into the PDF as white text; that PDF is the template
  and is uploaded on every call.
- **A field is as wide as its tag, and its height follows its width.** Checkbox
  fonts are computed to hit a target box width; ids are short because every
  character has to fit. This is why the ids read `mtn`/`gf`/`f1`.
- **Tags must be white, not invisible.** Text render mode 3 extracts fine
  locally and PandaDoc sees nothing — an upload came back with zero fields.
  White paints, so tags are kept clear of printed content; a test renders the
  artefact against the source and fails on one unexpected pixel.
- **Every tag id must be declared in the request's `fields` object**, even
  though the tag already carries role and type. An undeclared tag is dropped
  without a word.
- **Field roles are derived from geometry, not a table.** Names are
  `{role}__{name}`; on pages 1-2 the left column is the applicant's and the
  right the officer's, matching how the form is labelled. Add a row to the spec
  table and the role follows. The sponsor line is the one documented override.
- **The club's bank details and the letter's signature are build arguments.**
  They belong to named people and this repository is public, so the committed
  form has that column emptied (`scripts/redact_source_form.py`, which removes
  the text operators — a white box would leave the glyphs extractable) and
  `build_form_fields.py` draws them back from the environment. The Dockerfile
  supplies the same values to the form and to the email template in one build,
  so the two cannot disagree about where money goes. Unset means visible
  placeholders and a warning in the log, never a blank or a plausible wrong
  value. Guarded by `test_no_real_bank_details_are_committed`.
- **`tests/conftest.py` clears the configuration environment before every
  test.** `web.py` calls `load_dotenv()` at import, so without it a developer's
  own `.env` leaks into every test that imports the app, and the suite's result
  depends on the machine it runs on.
- **`PANDADOC_API_KEY` is deliberately not required at startup.** The email job
  shares `load_settings()` and must keep running without it.
- **The public relay never imports the credential-bearing code.** Slack cannot
  present a Google ID token, so its endpoint cannot be IAM-protected; the split
  is what keeps the Gmail refresh token and the PandaDoc key off the internet.
  `slack_web.py` reaches the private service over HTTP with a minted ID token,
  and `load_relay_settings()` does not know the other variables exist. Both are
  asserted in `tests/unit/test_boundaries.py`, not left to discipline.
- **Slack authorisation is membership of the admin channel**, not a list in an
  environment variable. A slash command is workspace-wide once installed, so the
  check is ours to make; making it the channel means adding an officer is an
  invite, with no deploy and no second list to forget.
- **The relay verifies the signature over the raw body, before anything else.**
  Re-serialising the parsed form changes the bytes and nothing verifies. It
  answers within Slack's three seconds and finishes in a background task, which
  is why that service alone is deployed `--no-cpu-throttling`.
- **Package is `clubops`; the Cloud Run services are `cbt-clubops` and
  `cbt-clubops-slack`.** Deliberately different, and allowed to stay that way:
  the package is renamed on its own schedule. Renaming a *service* mints a new
  URL — cheap for `cbt-clubops`, whose URL is only ever a Terraform reference,
  and expensive for `cbt-clubops-slack`, whose URL is typed by hand into Slack's
  slash-command configuration and is the one thing Terraform cannot reach.
- **Service accounts are named for what acts as them**, not for what they are:
  `-run` is a runtime identity (`cbt-clubops-run`, `cbt-clubops-slack-run`), its
  absence is a caller (`cbt-clubops-scheduler`). No `-sa` suffix — the email
  already ends in `.iam.gserviceaccount.com`. The runtime account reads secrets
  and can invoke nothing; the caller reads no secret. Merging them would let the
  credential that gets through the front door also read the Gmail refresh token.

## Standing exceptions

Do not "simplify" these — they have been considered:

- `integrations/ports.py` — three protocols with one implementation each. They
  are why the whole suite runs with no credentials and no network.
- The 29 cases in `tests/fixtures/reference_cases.json` — generated by running
  the deployed n8n Code nodes. They are the fidelity contract, not tests. The
  fee and email modules are diffed against them character for character.
- `domain/fee.py` and `domain/email_template.py` are ports of a published spec.
  "Simplifying" them means diverging from what guests already receive.
- The application document prefills **nothing**. The Total needs two facts a
  name and an email do not carry — standard vs reduced tier, and whether the
  25 EUR application fee is waived for an existing Toastmaster — so the form is
  placed and assigned, not filled. This is why `application_form.py` does not
  import `fee.py`.
- `scripts/preview_form_fields.py` looks redundant next to the tests. It is not:
  the tests check the geometry is *self-consistent*, and only the rendered PNGs
  show where the tags actually land on the page.
- `scripts/diagnose_pandadoc.py` looks like scratch debugging. Keep it. PandaDoc
  reports none of the ways a tag can fail — it returns 201 and produces a blank
  form — so `/details` is the only way to know what was actually placed.

## Commands

```bash
uv sync
uv run pytest                          # 295 tests, no network, no credentials
uv run python scripts/run_locally.py   # honours DRY_RUN in .env

uv run python scripts/build_form_fields.py     # regenerate the annotated PDF
uv run python scripts/preview_form_fields.py   # render it, then LOOK at the PNGs
uv run python scripts/create_application_doc.py --name "Ada Lovelace" \
    --email ada@example.com                    # honours DRY_RUN too
uv run --with ruff ruff check src tests scripts
```
