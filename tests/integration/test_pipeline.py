"""The workflow end to end, with fake Sheets / Gmail / Slack.

These are the behaviours that made the n8n workflow trustworthy, restated as
tests: the filter, the cutoff, the draft-before-mark ordering, per-row
isolation, and a single aggregated failure message.
"""

from __future__ import annotations

import pytest

from clubops.config import GoogleCredentialsConfig, PandaDocConfig, Settings
from clubops.domain.models import CivilDate, FeeConfig, Registration
from clubops.integrations.sheets import is_pending
from clubops.pipeline import run_membership_drafts

# --- Fakes ----------------------------------------------------------------


class FakeSource:
    def __init__(self, registrations: list[Registration]) -> None:
        self._registrations = registrations
        self.marked: list[tuple[int, str, str]] = []
        self.read_error: Exception | None = None
        self.mark_error: Exception | None = None

    def read_pending_registrations(self) -> list[Registration]:
        if self.read_error:
            raise self.read_error
        return self._registrations

    def mark_processed(self, row_number: int, marker: str, draft_id: str) -> None:
        if not draft_id:
            raise ValueError("no draft id")
        if self.mark_error:
            raise self.mark_error
        self.marked.append((row_number, marker, draft_id))


class FakeDrafts:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, str]] = []
        self.error: Exception | None = None

    def create_draft(self, to: str, subject: str, body_html: str) -> str:
        if self.error:
            raise self.error
        self.created.append((to, subject, body_html))
        return f"draft-{len(self.created)}"


class FakeNotifier:
    def __init__(self) -> None:
        self.posts: list[str] = []

    def post(self, text: str) -> None:
        self.posts.append(text)


# --- Fixtures -------------------------------------------------------------


def make_settings(**overrides) -> Settings:
    defaults = {
        "spreadsheet_id": "sheet-id",
        "sheet_name": "Form responses 1",
        "process_rows_after": CivilDate(2026, 8, 12),
        "date_order": "DMY",
        "slack_channel": "#cbt-clubops-admin",
        "slack_bot_token": "xoxb-test",
        "timezone": "Europe/Berlin",
        "google": GoogleCredentialsConfig("id", "secret", "refresh"),
        "pandadoc": PandaDocConfig("api-key", "officer@example.com", "Club Officer"),
        "fees": FeeConfig(),
        "dry_run": False,
        "service_name": "cbt-membership-agent",
        "project_id": "cbt",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def registration(
    row_number: int,
    timestamp: str,
    email: str = "guest@example.com",
    name: str = "Guest Name",
) -> Registration:
    return Registration(
        row_number=row_number,
        timestamp_raw=timestamp,
        guest_name=name,
        guest_email=email,
    )


@pytest.fixture
def parts():
    return FakeDrafts(), FakeNotifier()


# --- The happy path -------------------------------------------------------


def test_a_pending_guest_gets_a_draft_a_marker_and_a_slack_notice(parts):
    drafts, notifier = parts
    source = FakeSource([registration(2, "2026-08-20 09:00:00")])

    summary = run_membership_drafts(make_settings(), source, drafts, notifier)

    assert summary.processed == 1
    assert summary.skipped == 0
    assert summary.failed == 0

    (to, subject, body) = drafts.created[0]
    assert to == "guest@example.com"
    assert subject == "Your interest in joining Center Berlin Toastmasters"
    # 20 August shifts to September: the 7-month case.
    assert "7 x 21 + 25 = 172 Euros" in body

    assert len(source.marked) == 1
    row_number, marker, draft_id = source.marked[0]
    assert row_number == 2
    assert marker.startswith("processed 20")
    assert draft_id == "draft-1"

    assert len(notifier.posts) == 1
    assert "A membership draft is waiting in Gmail" in notifier.posts[0]
    assert "September 2026 - March 2027 (7 months)" in notifier.posts[0]


def test_the_marker_is_written_to_the_row_it_was_read_from(parts):
    drafts, notifier = parts
    source = FakeSource(
        [
            registration(5, "2026-08-20 09:00:00", "a@example.com"),
            registration(9, "2026-08-20 09:00:00", "b@example.com"),
        ]
    )

    run_membership_drafts(make_settings(), source, drafts, notifier)

    # Identical timestamps: n8n matched rows by Timestamp and would have
    # mismarked. Row numbers keep them distinct.
    assert [row for row, _, _ in source.marked] == [5, 9]


# --- Filtering and the cutoff ---------------------------------------------


def test_rows_older_than_the_cutoff_are_skipped_entirely(parts):
    drafts, notifier = parts
    source = FakeSource(
        [
            registration(2, "2026-08-11 09:00:00"),  # before go-live
            registration(3, "2026-08-12 09:00:00"),  # on go-live, included
        ]
    )

    summary = run_membership_drafts(make_settings(), source, drafts, notifier)

    assert summary.skipped == 1
    assert summary.processed == 1
    assert [row for row, _, _ in source.marked] == [3]


@pytest.mark.parametrize(
    "row,expected",
    [
        ({"Draft Status": "", "Your email address": "a@b.com"}, True),
        ({"Draft Status": "   ", "Your email address": "a@b.com"}, True),
        ({"Your email address": "a@b.com"}, True),
        (
            {"Draft Status": "processed 2026-08-19", "Your email address": "a@b.com"},
            False,
        ),
        ({"Draft Status": "", "Your email address": ""}, False),
        ({"Draft Status": "", "Your email address": "   "}, False),
        ({"Draft Status": ""}, False),
    ],
)
def test_the_row_filter_matches_n8n(row, expected):
    assert is_pending(row, "Draft Status", "Your email address") is expected


# --- The ordering guarantee ----------------------------------------------


def test_a_failed_draft_leaves_the_row_unmarked(parts):
    drafts, notifier = parts
    drafts.error = RuntimeError("gmail auth expired")
    source = FakeSource([registration(2, "2026-08-20 09:00:00")])

    summary = run_membership_drafts(make_settings(), source, drafts, notifier)

    assert summary.processed == 0
    assert summary.failed == 1
    # The guest is retried next run rather than silently lost.
    assert source.marked == []


def test_a_failed_sheet_write_is_reported_and_the_row_stays_unmarked(parts):
    drafts, notifier = parts
    source = FakeSource([registration(2, "2026-08-20 09:00:00")])
    source.mark_error = RuntimeError("sheets quota exceeded")

    summary = run_membership_drafts(make_settings(), source, drafts, notifier)

    assert summary.failed == 1
    assert source.marked == []
    # The draft was created first, on purpose: a duplicate draft next run is
    # visible and deletable, a lost guest is not.
    assert len(drafts.created) == 1
    assert "sheets quota exceeded" in notifier.posts[-1]


# --- Per-row isolation and failure reporting ------------------------------


def test_one_bad_row_does_not_affect_the_others(parts):
    drafts, notifier = parts
    source = FakeSource(
        [
            registration(2, "2026-08-20 09:00:00", "good1@example.com"),
            registration(3, "last Tuesday", "broken@example.com"),
            registration(4, "2026-08-20 09:00:00", "good2@example.com"),
        ]
    )

    summary = run_membership_drafts(make_settings(), source, drafts, notifier)

    assert summary.processed == 2
    assert summary.failed == 1
    assert [to for to, _, _ in drafts.created] == [
        "good1@example.com",
        "good2@example.com",
    ]


def test_a_run_posts_exactly_one_failure_message_listing_every_failure(parts):
    drafts, notifier = parts
    source = FakeSource(
        [
            registration(2, "not a date", "one@example.com"),
            registration(3, "", "two@example.com"),
        ]
    )

    summary = run_membership_drafts(
        make_settings(), source, drafts, notifier, trace_id="abc123"
    )

    assert summary.failed == 2
    failure_posts = [p for p in notifier.posts if "workflow failed" in p]
    assert len(failure_posts) == 1
    message = failure_posts[0]
    assert "*Failed rows:* 2" in message
    assert "row 2 (one@example.com)" in message
    assert "row 3 (two@example.com)" in message
    assert "abc123" in message
    assert "console.cloud.google.com/logs" in message


def test_slack_being_down_does_not_mask_a_row_failure(parts):
    drafts, _ = parts

    class BrokenNotifier:
        def post(self, text: str) -> None:
            raise RuntimeError("slack is down")

    source = FakeSource([registration(2, "not a date")])
    summary = run_membership_drafts(make_settings(), source, drafts, BrokenNotifier())
    assert summary.failed == 1


def test_an_unreadable_sheet_fails_the_whole_run_after_notifying(parts):
    drafts, notifier = parts
    source = FakeSource([])
    source.read_error = RuntimeError("spreadsheet not found")

    with pytest.raises(RuntimeError, match="spreadsheet not found"):
        run_membership_drafts(make_settings(), source, drafts, notifier)

    assert "could not read the sheet" in notifier.posts[-1]


# --- Dry run --------------------------------------------------------------


def test_dry_run_touches_nothing(parts):
    drafts, notifier = parts
    source = FakeSource([registration(2, "2026-08-20 09:00:00")])

    summary = run_membership_drafts(
        make_settings(dry_run=True), source, drafts, notifier
    )

    assert summary.processed == 1
    assert summary.dry_run is True
    assert drafts.created == []
    assert source.marked == []
    assert notifier.posts == []
