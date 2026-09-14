"""Slack message wording.

The draft-notice and failure messages reproduce the n8n Slack nodes. The
application-document ones below have no n8n ancestor and are ours to change.
"""

from __future__ import annotations

from clubops.domain.fee import calculate_fee
from clubops.domain.models import CivilDate
from clubops.domain.slack_messages import (
    RowFailure,
    format_number,
    render_document_accepted,
    render_document_dry_run,
    render_document_failed,
    render_document_ready,
    render_draft_ready,
    render_failure,
)


def test_numbers_render_as_n8n_interpolated_them():
    # A bare JS number: 54, not 54.00; 97.5, not 97.50.
    assert format_number(54) == "54"
    assert format_number(97.5) == "97.5"
    assert format_number(101.5) == "101.5"


def test_the_draft_notice_shows_the_working():
    quote = calculate_fee(CivilDate(2026, 8, 20))
    message = render_draft_ready(
        "Dee Late August", "dee@example.com", "2026-08-20", quote
    )
    assert message.splitlines() == [
        ":inbox_tray: *A membership draft is waiting in Gmail*",
        "*Guest:* Dee Late August",
        "*Email:* dee@example.com",
        "*Registered:* 2026-08-20",
        "*Membership starts:* September 2026",
        "*Period:* September 2026 - March 2027 (7 months)",
        "*Quoted:* 7 x 21 + 25 = 172 Euros",
        "*Reduced rate would be:* 126.5 Euros",
        "Review and send it from the CBT Gmail drafts folder.",
    ]


def test_the_failure_notice_names_every_failed_row():
    message = render_failure(
        [
            RowFailure(4, "one@example.com", "Unrecognised Timestamp format: soon"),
            RowFailure(7, "", "gmail auth expired"),
        ],
        service_name="cbt-membership-agent",
        trace_id="abc123",
        log_url="https://console.cloud.google.com/logs/query;query=x?project=cbt",
    )
    assert ":rotating_light: *CBT membership workflow failed*" in message
    assert "*Service:* cbt-membership-agent" in message
    assert "*Trace:* abc123" in message
    assert "*Failed rows:* 2" in message
    assert "• row 4 (one@example.com): Unrecognised Timestamp format: soon" in message
    assert "• row 7 ((no email)): gmail auth expired" in message
    assert "retried on the next run" in message
    assert "Open the logs for this run" in message


def test_the_failure_notice_works_without_a_log_url():
    message = render_failure([RowFailure(2, "a@b.com", "boom")], "svc", "")
    assert "Open the logs" not in message


# --- The application-document command -------------------------------------


def test_the_ack_names_the_guest():
    """It is what the board reads for the seconds the upload takes, so it has to
    confirm the command was understood, not merely that something is happening."""
    assert render_document_accepted("Ada Lovelace") == (
        "Creating the application document for Ada Lovelace…"
    )


def test_the_result_says_draft_and_carries_the_link():
    """The service cannot send the document. A message that did not say so would
    invite the assumption that it had."""
    text = render_document_ready(
        "Ada Lovelace",
        "ada@example.com",
        "jui",
        "https://app.pandadoc.com/a/#/documents/abc",
    )
    assert "Ada Lovelace" in text
    assert "ada@example.com" in text
    assert "https://app.pandadoc.com/a/#/documents/abc" in text
    assert "*draft*" in text
    assert "send it yourself" in text
    # Who asked for it: the audit trail the shared PandaDoc key cannot provide.
    assert "jui" in text


def test_a_dry_run_cannot_be_mistaken_for_a_success():
    """The failure mode this guards is somebody reading the message, believing a
    document exists, and never looking in PandaDoc again."""
    text = render_document_dry_run("CBT Membership Application - Ada", "ada@e.com")
    assert "nothing was created" in text
    assert "CBT Membership Application - Ada" in text


def test_a_failure_carries_the_underlying_error():
    """The background task has no caller to raise into; this text is the only
    thing between a failure and nobody knowing."""
    text = render_document_failed("Ada Lovelace", "ada@e.com", "PandaDoc said no")
    assert "Ada Lovelace" in text
    assert "PandaDoc said no" in text
