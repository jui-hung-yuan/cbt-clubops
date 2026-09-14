# Operating it

What to do once it is deployed. Setting it up is in [DEPLOY.md](DEPLOY.md).

---

## Calling the service by hand

The service is `--no-allow-unauthenticated`, so a plain `curl` gets 403. Two
traps here, both of which cost time the first time:

**`gcloud auth print-identity-token` alone does not work.** It mints a token
whose audience is gcloud's own client ID, not your service. Cloud Run rejects
it. You must impersonate the invoker account and set the audience:

```bash
export PROJECT_ID=cbt-space
URL=$(gcloud run services describe cbt-clubops \
        --project "$PROJECT_ID" --region europe-west1 --format="value(status.url)")

TOKEN=$(gcloud auth print-identity-token \
  --impersonate-service-account="cbt-clubops-scheduler@${PROJECT_ID}.iam.gserviceaccount.com" \
  --audiences="$URL")

curl -H "Authorization: Bearer $TOKEN" "$URL/healthcheck"
```

That impersonation needs `roles/iam.serviceAccountTokenCreator` on the invoker
account — **`roles/owner` does not include it**, deliberately. Granted once with:

```bash
gcloud iam service-accounts add-iam-policy-binding \
  "cbt-clubops-scheduler@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project "$PROJECT_ID" --member="user:<your-account>@gmail.com" \
  --role=roles/iam.serviceAccountTokenCreator
```

IAM changes take a minute or two to propagate; a `PERMISSION_DENIED` immediately
after granting usually just means waiting.

**The health route is `/healthcheck`, not `/healthz`.** Google's frontend
reserves `/healthz` on Cloud Run and answers it itself with a 404 before the
request reaches the container. The tell is that every *other* path returns 403
when unauthenticated while `/healthz` returns 404 — a pre-auth response means
the frontend, not your app.

---

## How it behaves when things go wrong

**The Gmail draft is created before the sheet is marked**, on purpose. If the
sheet write fails, the row stays unmarked and the guest is picked up next run
rather than being silently lost. The trade-off is the opposite failure mode —
a duplicate draft — which is visible and deletable. `mark_processed` requires the
draft id as an argument, so the ordering cannot be reversed by accident.

**Rows are isolated.** A malformed Timestamp fails that guest only; everyone else
in the run is unaffected. One aggregated Slack message lists every failed row,
with a link to the logs for that trace.

**A bot that is not in the channel** fails with `not_in_channel`, which reads
like a token problem and is not. Invite it: `/invite @YourAppName` in
`#cbt-clubops-admin`.

### The gap that carried over from n8n

Nothing tells you if the *service* stops running. If Cloud Scheduler is paused or
the service is broken at startup, there are no rows processed, so there are no
failures to report — and the Slack channel is quiet in exactly the same way it is
quiet when nobody has registered. Cloud Scheduler does surface failed attempts in
its own logs, which n8n did not, but a heartbeat is still worth adding once this
has been running a while.

---

---

## Changing the fee rules

Rates are environment variables, not constants — `STANDARD_MONTHLY_FEE`,
`REDUCED_MONTHLY_FEE`, `APPLICATION_FEE`, `CURRENT_MONTH_CUTOFF_DAY`. Changing
one is a `gcloud run services update --update-env-vars`, not a code change.

The *rules* (two 6-month terms, the September/March roll into 7 months, the
10th-of-the-month shift) live in `src/clubops/domain/fee.py` and are covered
by `tests/unit/test_fee.py`. Source: `src/clubops/assets/CBT_application_form_2026_fees_v2.pdf`.
