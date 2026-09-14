"""Wiring: build the real clients and run the workflow.

Kept separate from ``web`` so the HTTP layer stays thin, and separate
from ``pipeline`` so the workflow itself never names a concrete API client.
"""

from __future__ import annotations

import logging

from googleapiclient.discovery import build

from clubops.config import ConfigError, load_settings
from clubops.domain.application_form import document_name
from clubops.domain.models import DEFAULT_CLUB_DETAILS
from clubops.integrations.gmail import GmailDraftCreator
from clubops.integrations.google_auth import (
    assert_granted_scopes,
    build_credentials,
)
from clubops.integrations.pandadoc import (
    PandaDocApplicationCreator,
    build_document_payload,
    document_link,
)
from clubops.integrations.sheets import SheetsRegistrationSource
from clubops.integrations.slack import SlackNotifier
from clubops.pipeline import RunSummary, run_membership_drafts

logger = logging.getLogger(__name__)


def run_membership_draft_job(trace_id: str = "") -> RunSummary:
    """Entry point for the scheduled run."""
    settings = load_settings()
    logger.info(
        "starting membership draft run (dry_run=%s, sheet=%r)",
        settings.dry_run,
        settings.sheet_name,
    )
    if settings.club == DEFAULT_CLUB_DETAILS:
        # Loud, because the letters this run drafts will tell guests to transfer
        # money to DE00 0000... The failure is safe but it is still a failure,
        # and the first place anyone looks is the log for the run.
        logger.warning(
            "club details are unset: every draft will show the placeholder IBAN "
            "and signature. Pass BANK_IBAN, BANK_BIC, BANK_NAME, BANK_OWNER and "
            "SIGNATURE_NAME as build args — see docs/DEPLOY.md."
        )

    credentials = build_credentials(settings.google, settings.scopes)
    # Verified every run rather than once at startup: a token re-minted with a
    # broader scope must not silently become sendable between deploys.
    assert_granted_scopes(credentials, settings.scopes)

    sheets_service = build(
        "sheets", "v4", credentials=credentials, cache_discovery=False
    )
    gmail_service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    return run_membership_drafts(
        settings=settings,
        source=SheetsRegistrationSource(sheets_service, settings),
        drafts=GmailDraftCreator(gmail_service),
        notifier=SlackNotifier(settings.slack_bot_token, settings.slack_channel),
        trace_id=trace_id,
    )


def run_application_document_job(
    guest_name: str, guest_email: str, trace_id: str = ""
) -> dict[str, str]:
    """Create one membership application document in PandaDoc, in draft.

    Triggered by hand rather than by the scheduler: the gate is whether a guest
    has paid and wants to join, which is a judgement nobody has asked this
    service to make. Returns the id and the link a human opens to review it.
    """
    settings = load_settings()
    if not settings.pandadoc.api_key:
        raise ConfigError("missing required environment variable: PANDADOC_API_KEY")

    logger.info(
        "creating application document for %s (dry_run=%s, trace=%s)",
        guest_email,
        settings.dry_run,
        trace_id,
    )

    if settings.dry_run:
        # Matches the email job: a dry run validates and renders, but creates
        # nothing. Uploading would create a real document there is no undo for.
        payload = build_document_payload(
            guest_name,
            guest_email,
            settings.pandadoc.officer_email,
            settings.pandadoc.officer_name,
        )
        logger.info("DRY_RUN: would create %r", payload["name"])
        return {
            "document_id": "",
            "link": "",
            "name": payload["name"],
            "dry_run": "true",
        }

    creator = PandaDocApplicationCreator(
        api_key=settings.pandadoc.api_key,
        officer_email=settings.pandadoc.officer_email,
        officer_name=settings.pandadoc.officer_name,
    )
    document_id = creator.create_application_document(guest_name, guest_email)
    return {
        "document_id": document_id,
        "link": document_link(document_id),
        "name": document_name(guest_name),
        "dry_run": "false",
    }
