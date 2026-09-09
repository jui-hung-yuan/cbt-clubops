"""The membership draft run.

This is the whole workflow, in the order n8n ran it. It depends only on the
protocols in ``integrations.ports``, so the same logic drives the real Google
APIs, a test fake, and — if it is ever wanted — agent tools or an MCP server.

Two properties are load-bearing and deliberately structural rather than
conventional:

* **The draft is created before the row is marked.** ``mark_processed`` requires
  the draft id, so it cannot be called before a draft exists. If the sheet write
  fails, the row stays unmarked and the guest is retried next run. The cost is a
  possible duplicate draft, which is visible and deletable; a lost guest is not.
* **Rows are isolated.** One malformed Timestamp fails that guest only. Every
  other guest in the run is unaffected, and one aggregated failure message is
  posted at the end.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from urllib.parse import quote as urlquote
from zoneinfo import ZoneInfo

from clubops.config import Settings
from clubops.domain.email_template import render_membership_email
from clubops.domain.fee import calculate_fee
from clubops.domain.slack_messages import (
    RowFailure,
    render_draft_ready,
    render_failure,
)
from clubops.domain.timestamps import is_before_cutoff, parse_timestamp
from clubops.integrations.ports import (
    DraftCreator,
    Notifier,
    RegistrationSource,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunSummary:
    """What one run did. Returned to Cloud Scheduler as JSON."""

    processed: int
    skipped: int
    failed: int
    dry_run: bool


def build_log_url(project_id: str, trace_id: str) -> str | None:
    """A Cloud Logging link scoped to this run.

    Replaces n8n's "link to workflow execution", which has no equivalent here.
    """
    if not project_id or not trace_id:
        return None
    query = urlquote(f'trace="projects/{project_id}/traces/{trace_id}"')
    return (
        f"https://console.cloud.google.com/logs/query;query={query}"
        f"?project={project_id}"
    )


def processed_marker(settings: Settings) -> str:
    """The Draft Status value, e.g. "processed 2026-08-27".

    Computed in Europe/Berlin, not UTC: Cloud Run runs in UTC, so a run at 23:00
    Berlin time would otherwise stamp the following day's date for half the year.
    """
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return f"processed {today.isoformat()}"


def run_membership_drafts(
    settings: Settings,
    source: RegistrationSource,
    drafts: DraftCreator,
    notifier: Notifier,
    trace_id: str = "",
) -> RunSummary:
    """Read pending registrations, draft each guest's email, record progress."""
    failures: list[RowFailure] = []

    try:
        registrations = source.read_pending_registrations()
    except Exception as exc:
        # Nothing has been touched yet, so this is the one case that fails the
        # whole run. Report it, then let the caller surface a 5xx.
        logger.exception("could not read the registration sheet")
        _safe_notify(
            notifier,
            render_failure(
                [RowFailure(0, "", f"could not read the sheet: {exc}")],
                settings.service_name,
                trace_id,
                build_log_url(settings.project_id, trace_id),
            ),
        )
        raise

    marker = processed_marker(settings)
    processed = 0
    skipped = 0

    for registration in registrations:
        try:
            registered_on = parse_timestamp(
                registration.timestamp_raw, settings.date_order
            )

            if is_before_cutoff(registered_on, settings.process_rows_after):
                # Rows older than the go-live cutoff are ignored entirely, which
                # is why historic rows never need a manual backfill.
                logger.info(
                    "row %d registered %s predates the cutoff; skipping",
                    registration.row_number,
                    registered_on.iso,
                )
                skipped += 1
                continue

            quote = calculate_fee(registered_on, settings.fees)
            email = render_membership_email(
                registration.guest_name, quote, settings.club
            )

            if settings.dry_run:
                logger.info(
                    "DRY_RUN: would draft %r to %s (%s, %s)",
                    email.subject,
                    registration.guest_email,
                    quote.period,
                    quote.calculation_line,
                )
                processed += 1
                continue

            draft_id = drafts.create_draft(
                to=registration.guest_email,
                subject=email.subject,
                body_html=email.body_html,
            )
            # Only now, with a draft that exists, is the row marked.
            source.mark_processed(registration.row_number, marker, draft_id)
            notifier.post(
                render_draft_ready(
                    registration.guest_name,
                    registration.guest_email,
                    registered_on.iso,
                    quote,
                )
            )
            processed += 1

        except Exception as exc:
            logger.exception("row %d failed", registration.row_number)
            failures.append(
                RowFailure(
                    row_number=registration.row_number,
                    guest_email=registration.guest_email,
                    error=str(exc),
                )
            )

    if failures:
        _safe_notify(
            notifier,
            render_failure(
                failures,
                settings.service_name,
                trace_id,
                build_log_url(settings.project_id, trace_id),
            ),
        )

    summary = RunSummary(
        processed=processed,
        skipped=skipped,
        failed=len(failures),
        dry_run=settings.dry_run,
    )
    logger.info("run complete: %s", asdict(summary))
    return summary


def _safe_notify(notifier: Notifier, text: str) -> None:
    """Post a failure notice, but never let Slack being down mask the failure."""
    try:
        notifier.post(text)
    except Exception:
        logger.exception("could not post the failure notice to Slack")
