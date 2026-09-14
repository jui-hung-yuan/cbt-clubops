# Slack — the app, the tokens, the slash command

Everything the CBT Slack workspace needs to know about this service, and
everything this service needs to know about Slack. Deploy and Google Cloud live
in `DEPLOY.md`; this file is the one to open when Slack is the thing that is
wrong.

Two separate things use Slack, and they are easy to confuse:

| | posts the twice-weekly notices | runs `/application-doc` |
|---|---|---|
| service | `cbt-clubops` (private) | `cbt-clubops-slack` (public) |
| credential | bot token (`xoxb-…`) | bot token **and** signing secret |
| direction | service → Slack | Slack → service |
| trigger | Cloud Scheduler | a board member typing |

They are the **same Slack app**. One app, one bot token, one signing secret —
adding the slash command does not mean creating a second app.

---

## 1. The app and the bot token — how the existing one was made

If you are reading this because you have forgotten: the app already exists, and
you do not need to recreate it. Find it at **https://api.slack.com/apps**,
signed in to the CBT workspace. It is the app whose bot is a member of
`#cbt-clubops-admin`.

The token in Secret Manager as `cbt-slack-bot-token` came from that app's
**OAuth & Permissions** page. To read it again rather than re-mint it:

1. https://api.slack.com/apps → the app
2. **OAuth & Permissions** → **Bot User OAuth Token**, starting `xoxb-`

Copy it from there; it does not expire and re-installing is not necessary. The
value is shown in full to workspace admins, so there is nothing to recover.

### Recreating it from nothing

Only if the app has actually been deleted. Recorded so it can be rebuilt.

1. **https://api.slack.com/apps → Create New App → From scratch.** Name it
   something a future board will recognise (`CBT Membership`), pick the CBT
   workspace.
2. **OAuth & Permissions → Scopes → Bot Token Scopes.** Add:

   | scope | why |
   |---|---|
   | `chat:write` | post the draft notices and command results |
   | `commands` | receive `/application-doc` |
   | `groups:read` | read who is in a **private** admin channel |
   | `channels:read` | the same, if the channel is **public** |

   `groups:read` and `channels:read` are different scopes for the same question,
   and Slack picks by channel type, not by which one sounds right. A private
   channel with only `channels:read` fails with `missing_scope` — see
   §5. Granting both costs nothing.
3. **Install to Workspace.** This is when the `xoxb-` token appears. Changing
   scopes later requires re-installing before the new scope takes effect; the
   token itself stays the same.
4. **Invite the bot to the channel**: `/invite @CBT Membership` in
   `#cbt-clubops-admin`. Installing the app does *not* put the bot in any
   channel, and this is the single most common cause of a working token that
   still cannot post.
5. Store it:

   ```bash
   printf '%s' "xoxb-..." | gcloud secrets versions add cbt-slack-bot-token \
     --data-file=- --project cbt-space
   ```

---

## 2. The signing secret

New requirement, for the slash command only. It is how the public service knows
a request genuinely came from Slack — see §4.

**Basic Information → App Credentials → Signing Secret** → *Show*.

```bash
gcloud secrets create cbt-slack-signing-secret \
  --replication-policy=automatic --project cbt-space
printf '%s' "<the signing secret>" | \
  gcloud secrets versions add cbt-slack-signing-secret --data-file=- --project cbt-space
```

It is not the bot token, not the app-level token (`xapp-`), and not the client
secret. It is the only one of the four that is never sent anywhere — both sides
hold a copy and compare hashes.

---

## 3. The slash command

**Slash Commands → Create New Command.**

| field | value |
|---|---|
| Command | `/application-doc` |
| Request URL | `https://<relay URL>/slack/commands/application-doc` |
| Short Description | `Create a membership application document for a guest` |
| Usage Hint | `Ada Lovelace ada@example.com` |

The Request URL needs the relay deployed first, because Slack verifies it is
reachable when you save. Deploy, then come back and fill it in — the order is in
`DEPLOY.md`.

### Socket Mode must be off

If **Settings → Socket Mode** is enabled, Slack hides the Request URL field and
tells you none is needed. That is true, and it is the wrong mode for us.

Socket Mode has the app open a WebSocket *out* to Slack, so Slack never calls
in. That needs a process holding a connection open permanently — which means
`min-instances = 1`, an instance running 24 hours a day for a command used a few
times a month. Cloud Run scales to zero otherwise and costs nothing while idle.

The trade being turned down is real: Socket Mode would remove the public URL,
the signature verification and the entire `cbt-clubops-slack` service. It is the
simpler security story, and it is worth revisiting if the club ever runs
something always-on. On serverless it does not fit.

> **A slash command is workspace-wide.** There is no setting that scopes it to a
> channel. Once installed, anyone in the workspace can type `/application-doc`
> anywhere, including in a DM with themselves. That is why the service does its
> own authorisation, which is the next section.

### Where it may be run

**Only in the admin channel.** Slack offers no setting for this — installing the
app makes the command available in every channel and every DM — so the relay
checks `channel_id` itself and refuses anywhere else.

This is not access control: anyone it turns away is a channel member who could
walk into the channel and run it there. It is what keeps the result visible. The
link is posted to the `response_url`, which points wherever the command was
typed, so a run from a DM would create a real application document that the rest
of the board never sees.

The check happens before the membership lookup, so a command typed in the wrong
place costs no Slack API call.

### Who is allowed to run it

Membership of the admin channel. Not a list in an environment variable.

`SLACK_ADMIN_CHANNEL_ID` names one channel; the relay asks
`conversations.members` whether the person who typed the command is in it, and
refuses politely if not. So:

- adding an incoming officer is an **invite**
- removing an outgoing one is a **kick**
- neither is a deploy, and there is no second list to forget to update

**Keep the channel private.** In a public channel anyone can join themselves,
and the ACL means nothing.

The answer is cached for 60 seconds, so a removal takes up to a minute to bite.

### Finding the channel id

`SLACK_ADMIN_CHANNEL_ID` is an id like `C0123456789`, **not** `#cbt-clubops-admin`
— `conversations.members` takes only ids. In Slack: right-click the channel →
**View channel details** → scroll to the bottom, where the id is printed with a
copy button. (`C…` for a public channel, `G…` for some older private ones.)

`SLACK_CHANNEL` — used by the twice-weekly job for `chat.postMessage` — stays a
`#name`. Two variables, two formats, deliberately: `chat.postMessage` resolves
names and reads better in the deploy command, membership lookup does not.

---

## 4. Why the public endpoint is safe

The relay is the only part of this system reachable without IAM, because Slack's
servers cannot present a Google ID token. Its front door is a shared secret
instead.

On every request Slack sends two headers — `X-Slack-Request-Timestamp` and
`X-Slack-Signature` — where the signature is `HMAC-SHA256` of the string
`v0:{timestamp}:{raw body}`, keyed with the signing secret. The relay computes
the same thing and compares. Only Slack can produce a match, because only Slack
has the key. The secret itself never travels.

Four details, each of which is a test in `tests/unit/test_slack_command.py`:

- **The raw body, not the parsed form.** Re-serialising a parsed form reorders
  and re-escapes parameters, and then nothing ever verifies. `slack_web.py`
  reads `await request.body()` first and parses that same string with
  `parse_qs`.
- **Constant-time comparison** (`hmac.compare_digest`). A plain `==` returns
  sooner the earlier it finds a mismatched byte; timed carefully that recovers a
  valid signature one byte at a time.
- **Requests older than five minutes are refused**, even though their signature
  is still perfectly valid. A captured request stays signed forever; the window
  is what makes replaying it useless.
- **A blank secret fails closed.** An unset environment variable must not mean
  "everything verifies".

An unsigned request gets `401` and no explanation. Everything else — a typo, an
outsider, a broken downstream — gets `200` with text, because `200` is how Slack
is told to show a message to the person who typed the command.

Traffic you did not send will arrive; scanners sweep `*.run.app`. It fails at
the signature check, which is one hash and no network calls, and reaches neither
Slack's API nor PandaDoc. `--max-instances` on the relay is what bounds the cost
of someone doing it deliberately.

---

## 5. When Slack is the thing that is wrong

| symptom | cause |
|---|---|
| `not_in_channel` | The bot is not in the channel. `/invite @CBT Membership`. Reads like a token problem; is not. |
| `missing_scope` on the members lookup | Private channel with only `channels:read`. Add `groups:read` **and re-install the app** — a new scope does nothing until re-installation. |
| `channel_not_found` | `SLACK_ADMIN_CHANNEL_ID` is a `#name`, or an id from a different workspace. |
| `invalid_auth` | The token is not the `xoxb-` bot token. `xoxp-` (user) and `xapp-` (app-level) both look plausible and neither works. |
| `/application-doc` says "operation timed out" | The relay took over 3s to ack. It should ack immediately and defer; check the relay is deployed with `--no-cpu-throttling` (see `DEPLOY.md`). |
| The ack appears, the result never does | The background task died after the response. Same cause as above, or the relay lacks `roles/run.invoker` on the private service — the logs will say. |
| `dispatch_failed` | Slack could not reach the Request URL at all. Usually the relay is deployed `--no-allow-unauthenticated` and Google is returning 403 before the request arrives. |
| Everything returns 401, signature never matches | The signing secret in Secret Manager is stale (it changes if the app is recreated), or something re-serialised the body. |
| Only you can run the command | Everyone else is outside the admin channel. That is the design; invite them. |
| "Run `/application-doc` in the membership admin channel" | It was typed somewhere else — another channel, or a DM. The command only works in the channel named by `SLACK_ADMIN_CHANNEL_ID`. |

To see what the relay thought:

```bash
gcloud logging read 'resource.type="cloud_run_revision"
  AND resource.labels.service_name="cbt-clubops-slack"' \
  --project cbt-space --limit 50 --freshness=10m \
  --format="value(jsonPayload.message,textPayload)"
```

`rejected an unsigned request` is scanner noise and expected. `denied
/application-doc for …` is a real person being refused, and names them.

---

## 6. Rotating a credential

Both are read from Secret Manager at container start, so a new version needs a
revision restart to take effect:

```bash
printf '%s' "<new value>" | gcloud secrets versions add cbt-slack-bot-token \
  --data-file=- --project cbt-space

gcloud run services update cbt-clubops --project cbt-space \
  --region europe-west1 --update-env-vars ROTATED_AT=$(date +%s)
```

The dummy env var exists only to force a new revision; `--set-secrets` with
`:latest` pins the version at start, so adding a version alone changes nothing
on a running service. Do the same for `cbt-clubops-slack` when rotating the
signing secret.

Rotate when: a board member with workspace admin rights leaves, the token
appears anywhere it should not (a laptop, a screenshot, a message), or the app
is recreated for any reason.
