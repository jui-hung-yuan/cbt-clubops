"""The public half of the split: Slack's entry point.

This is the only service on the internet. Slack cannot present a Google ID
token, so its endpoint cannot be IAM-protected, and everything reachable from a
public URL is therefore kept in here — where the only secret is Slack's signing
secret. The club's Gmail refresh token and the PandaDoc key stay on
``cbt-clubops``, which remains ``--no-allow-unauthenticated`` and is
called from here with a minted ID token.

Three rules shape the route below, all of them Slack's:

1. **Answer within three seconds** or the board member sees "operation timed
   out". Creating a PandaDoc document takes longer than that, so the route acks
   immediately and finishes the work in a background task, reporting back to the
   one-shot ``response_url``.
2. **Verify the signature over the raw body.** Re-serialising the parsed form
   changes the bytes and every signature then fails.
3. **A slash command is workspace-wide.** Installing the app does not scope it
   to a channel: anyone in the workspace can type it anywhere. Authorisation is
   therefore ours to do, and it is membership of the admin channel.
"""

from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from urllib.parse import parse_qs

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from clubops.config import ConfigError, RelaySettings, load_relay_settings
from clubops.domain.slack_command import (
    CommandUsageError,
    SlackSignatureError,
    parse_application_command,
    verify_signature,
)
from clubops.domain.slack_messages import (
    render_document_accepted,
    render_document_dry_run,
    render_document_failed,
    render_document_ready,
)
from clubops.integrations.run_invoker import MembershipServiceClient
from clubops.integrations.slack import (
    SlackChannelMembership,
    SlackError,
    post_deferred_reply,
)
from clubops.observability import setup_logging

load_dotenv()
setup_logging()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="cbt-clubops-slack",
    description="Slack slash commands for CBT club operations.",
)


@lru_cache(maxsize=1)
def _settings() -> RelaySettings:
    """Load once per process.

    Lazily rather than at import: a configuration mistake should fail the slash
    command with a message in the channel, not take down the health check Cloud
    Run uses to decide whether the revision is serving at all.
    """
    return load_relay_settings()


@lru_cache(maxsize=1)
def _membership() -> SlackChannelMembership:
    settings = _settings()
    return SlackChannelMembership(settings.bot_token, settings.admin_channel_id)


def _ephemeral(text: str) -> JSONResponse:
    """A reply only the person who typed the command can see."""
    return JSONResponse(
        status_code=200, content={"response_type": "ephemeral", "text": text}
    )


@app.get("/healthcheck")
def healthcheck() -> dict[str, str]:
    """Liveness check. Not ``/healthz``; see web.py for why."""
    return {"status": "ok"}


@app.post("/slack/commands/application-doc")
async def application_doc_command(
    request: Request, background: BackgroundTasks
) -> Response:
    """Handle ``/application-doc Ada Lovelace ada@example.com``.

    Every failure below answers 200 with an explanation, except an unverifiable
    signature, which answers 401 and says nothing. A 200 is how Slack is told to
    show text to the user; a non-2xx shows them a generic error and hides the
    reason. But an unsigned request is not a user — it is whoever found the URL,
    and it is told only that it failed.
    """
    # Before any parsing: the signature covers these exact bytes.
    raw_body = (await request.body()).decode("utf-8")

    try:
        settings = _settings()
    except ConfigError as exc:
        logger.error("relay is misconfigured: %s", exc)
        return _ephemeral(
            "The membership relay is misconfigured and cannot run commands. "
            "Check the service logs."
        )

    try:
        verify_signature(
            signing_secret=settings.signing_secret,
            timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
            body=raw_body,
            signature=request.headers.get("X-Slack-Signature", ""),
            now=time.time(),
        )
    except SlackSignatureError as exc:
        logger.warning("rejected an unsigned request: %s", exc)
        return Response(status_code=401)

    # Parsed from the bytes already read rather than via request.form(): the
    # body is urlencoded, we hold it, and Starlette's form parser would pull in
    # python-multipart for a job the standard library already does.
    form = {k: v[0] for k, v in parse_qs(raw_body).items()}
    user_id = form.get("user_id", "")
    user_name = form.get("user_name", "someone")
    response_url = form.get("response_url", "")

    try:
        if not _membership().allows(user_id, now=time.time()):
            logger.warning("denied /application-doc for %s (%s)", user_name, user_id)
            return _ephemeral(
                "Only members of the membership admin channel can create "
                "application documents. Ask a board member to add you."
            )
    except SlackError as exc:
        logger.error("could not check channel membership: %s", exc)
        return _ephemeral(f"Could not check who is in the admin channel: {exc}")

    try:
        guest_name, guest_email = parse_application_command(form.get("text", ""))
    except CommandUsageError as exc:
        return _ephemeral(str(exc))

    if not response_url:
        # Only reachable from a hand-made request; without it there is nowhere to
        # report to, and the work would succeed invisibly.
        return _ephemeral("Slack sent no response_url, so there is nothing to reply to.")

    background.add_task(
        _create_and_report,
        base_url=settings.core_service_url,
        response_url=response_url,
        guest_name=guest_name,
        guest_email=guest_email,
        requested_by=user_name,
    )

    logger.info("accepted /application-doc for %s from %s", guest_email, user_name)
    return _ephemeral(render_document_accepted(guest_name))


def _create_and_report(
    *,
    base_url: str,
    response_url: str,
    guest_name: str,
    guest_email: str,
    requested_by: str,
) -> None:
    """The part that outlives the ack.

    Runs after the response is sent, which on Cloud Run needs the service
    deployed with ``--no-cpu-throttling`` — CPU is otherwise withdrawn the
    instant the response completes and this would stall until the next request
    happened to wake the instance.

    Never raises: nothing is waiting to catch it, and a failure the board cannot
    see is worse than one written in the channel.
    """
    try:
        client = MembershipServiceClient(base_url)
        result = client.create_application_document(guest_name, guest_email)
    except Exception as exc:
        logger.exception("failed to create the application document")
        _report(response_url, render_document_failed(guest_name, guest_email, str(exc)))
        return

    if result.get("dry_run") == "true":
        _report(
            response_url,
            render_document_dry_run(result.get("name", guest_name), guest_email),
        )
        return

    _report(
        response_url,
        render_document_ready(
            guest_name, guest_email, requested_by, result.get("link", "")
        ),
    )


def _report(response_url: str, text: str) -> None:
    """Post the deferred reply, swallowing a failure to post it.

    If Slack itself is unreachable there is nothing further to try; the log line
    is the last record either way.
    """
    try:
        post_deferred_reply(response_url, text)
    except Exception:
        logger.exception("could not post the deferred reply to Slack")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
