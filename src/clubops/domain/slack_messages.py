"""Slack message bodies.

Pure rendering, kept out of ``integrations/slack.py`` so the wording is testable
without a network. The text reproduces the n8n Slack nodes; only the identifiers
in the failure message change, because n8n execution IDs do not exist on Cloud
Run (see ``render_failure``).
"""

from __future__ import annotations

from dataclasses import dataclass

from clubops.domain.models import Quote


def format_number(amount: float) -> str:
    """Render a number the way an n8n expression interpolated it: 54, or 97.5.

    Deliberately not the email's ``format_euro`` — the Slack message showed a
    bare JavaScript number, so "97.5" rather than "97.50".
    """
    return str(int(amount)) if float(amount).is_integer() else str(amount)


def render_draft_ready(
    guest_name: str, guest_email: str, registered_on_iso: str, quote: Quote
) -> str:
    """The per-guest notice posted after a draft is created and the row marked."""
    return (
        ":inbox_tray: *A membership draft is waiting in Gmail*\n"
        f"*Guest:* {guest_name}\n"
        f"*Email:* {guest_email}\n"
        f"*Registered:* {registered_on_iso}\n"
        f"*Membership starts:* {quote.start_month_name} {quote.start_year}\n"
        f"*Period:* {quote.period} ({quote.months} months)\n"
        f"*Quoted:* {quote.calculation_line}\n"
        f"*Reduced rate would be:* {format_number(quote.total_reduced)} Euros\n"
        "Review and send it from the CBT Gmail drafts folder."
    )


@dataclass(frozen=True, slots=True)
class RowFailure:
    """One row that failed, identified well enough to find it in the sheet."""

    row_number: int
    guest_email: str
    error: str


def render_failure(
    failures: list[RowFailure],
    service_name: str,
    trace_id: str,
    log_url: str | None = None,
) -> str:
    """The failure notice.

    n8n reported only the first failure per run; this lists every failed row,
    since a run can now fail several rows independently and a single example
    would hide the rest.
    """
    lines = [
        ":rotating_light: *CBT membership workflow failed*",
        f"*Service:* {service_name}",
        f"*Trace:* {trace_id}",
        f"*Failed rows:* {len(failures)}",
    ]
    for failure in failures:
        who = failure.guest_email or "(no email)"
        lines.append(f"• row {failure.row_number} ({who}): {failure.error}")
    lines.append(
        "No sheet row was marked as processed for these, so the affected guests "
        "are retried on the next run."
    )
    if log_url:
        lines.append(f"<{log_url}|Open the logs for this run>")
    return "\n".join(lines)


# --- The application-document command -------------------------------------
# These four have no n8n ancestor: the PandaDoc flow did not exist there. So
# unlike everything above, the wording is ours to change — nothing diffs them
# against reference_cases.json.


def render_document_accepted(guest_name: str) -> str:
    """The instant acknowledgement, seen only by whoever typed the command.

    Slack shows "operation timed out" if the route takes more than three
    seconds, so this is what the board reads while the document is being made.
    """
    return f"Creating the application document for {guest_name}…"


def render_document_ready(
    guest_name: str, guest_email: str, requested_by: str, link: str
) -> str:
    """The result, posted where the whole admin channel can see it.

    Says "draft" explicitly. The service cannot send the document and must not
    be assumed to have done so.
    """
    return (
        f":page_facing_up: Application document ready for *{guest_name}* "
        f"({guest_email}), requested by {requested_by}.\n"
        f"{link}\n"
        "It is a *draft* — open it, check it, and send it yourself."
    )


def render_document_dry_run(document_name: str, guest_email: str) -> str:
    """What a dry run reports.

    Distinct wording from the real thing on purpose: a dry run that reads like a
    success is how somebody concludes the document was created and stops looking.
    """
    return (
        f":test_tube: DRY_RUN is on, so nothing was created. Would have made "
        f"*{document_name}* for {guest_email}."
    )


def render_document_failed(guest_name: str, guest_email: str, error: str) -> str:
    """A failure, in the channel rather than only in the logs.

    The background task has no caller waiting on it, so this message is the only
    thing standing between a failure and nobody knowing.
    """
    return (
        f":x: Could not create the application document for *{guest_name}* "
        f"({guest_email}): {error}"
    )
