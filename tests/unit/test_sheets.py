"""The Sheets adapter: reading rows and writing the processed marker."""

from __future__ import annotations

import pytest

from clubops.config import GoogleCredentialsConfig, PandaDocConfig, Settings
from clubops.domain.models import CivilDate, FeeConfig
from clubops.integrations.sheets import (
    SheetsRegistrationSource,
    SheetStructureError,
    column_letter,
)

HEADERS = [
    "Timestamp",
    "First and last name",
    "Your email address",
    "GDPR consent",
    "Draft Status",
]


class FakeValues:
    """Mimics service.spreadsheets().values()."""

    def __init__(self, rows: list[list[str]]) -> None:
        self.rows = rows
        self.updates: list[dict] = []

    def get(self, **kwargs):
        self.last_get = kwargs
        return _Executable({"values": self.rows})

    def update(self, **kwargs):
        self.updates.append(kwargs)
        return _Executable({"updatedCells": 1})


class _Executable:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeService:
    def __init__(self, values: FakeValues) -> None:
        self._values = values

    def spreadsheets(self):
        return self

    def values(self):
        return self._values


def make_settings() -> Settings:
    return Settings(
        spreadsheet_id="sheet-id",
        sheet_name="Form responses 1",
        process_rows_after=CivilDate(2026, 8, 12),
        date_order="DMY",
        slack_channel="#cbt-clubops-admin",
        slack_bot_token="xoxb",
        timezone="Europe/Berlin",
        google=GoogleCredentialsConfig("id", "secret", "refresh"),
        pandadoc=PandaDocConfig("api-key", "officer@example.com", "Club Officer"),
        fees=FeeConfig(),
        dry_run=False,
        service_name="svc",
        project_id="cbt",
    )


def make_source(rows: list[list[str]]) -> tuple[SheetsRegistrationSource, FakeValues]:
    values = FakeValues(rows)
    return SheetsRegistrationSource(FakeService(values), make_settings()), values


def test_column_letters_cover_past_z():
    assert column_letter(0) == "A"
    assert column_letter(4) == "E"
    assert column_letter(25) == "Z"
    assert column_letter(26) == "AA"
    assert column_letter(27) == "AB"
    assert column_letter(51) == "AZ"
    assert column_letter(52) == "BA"
    with pytest.raises(ValueError):
        column_letter(-1)


def test_only_unprocessed_rows_with_an_email_are_returned():
    source, _ = make_source(
        [
            HEADERS,
            ["2026-08-20", "Ann Pending", "ann@example.com", "yes", ""],
            [
                "2026-08-20",
                "Bob Done",
                "bob@example.com",
                "yes",
                "processed 2026-08-19",
            ],
            ["2026-08-20", "Cal NoEmail", "", "yes", ""],
        ]
    )
    pending = source.read_pending_registrations()
    assert [r.guest_email for r in pending] == ["ann@example.com"]


def test_row_numbers_account_for_the_header_row():
    source, _ = make_source(
        [
            HEADERS,
            ["2026-08-20", "Ann", "ann@example.com", "yes", "processed 2026-08-19"],
            ["2026-08-20", "Bob", "bob@example.com", "yes", ""],
        ]
    )
    pending = source.read_pending_registrations()
    # Bob is the second data row, so sheet row 3.
    assert pending[0].row_number == 3


def test_trailing_empty_cells_are_padded():
    """Sheets truncates trailing blanks, so a pending row is often short."""
    source, _ = make_source([HEADERS, ["2026-08-20", "Ann", "ann@example.com"]])
    pending = source.read_pending_registrations()
    assert len(pending) == 1
    assert pending[0].guest_name == "Ann"


def test_names_and_emails_are_trimmed():
    source, _ = make_source(
        [HEADERS, ["2026-08-20", "  Ann Spaced  ", "  ann@example.com ", "yes", ""]]
    )
    pending = source.read_pending_registrations()
    assert pending[0].guest_name == "Ann Spaced"
    assert pending[0].guest_email == "ann@example.com"


def test_the_draft_status_column_is_found_by_name_not_position():
    """A Google Form edit inserts its new column before Draft Status."""
    shifted = [
        "Timestamp",
        "First and last name",
        "Your email address",
        "GDPR consent",
        "How did you hear about us",
        "Draft Status",
    ]
    source, values = make_source(
        [shifted, ["2026-08-20", "Ann", "ann@example.com", "yes", "a friend", ""]]
    )
    source.read_pending_registrations()
    source.mark_processed(2, "processed 2026-08-27", "draft-1")
    assert values.updates[0]["range"] == "'Form responses 1'!F2"


def test_a_missing_draft_status_column_is_a_clear_error():
    source, _ = make_source([HEADERS[:-1], ["2026-08-20", "Ann", "a@b.com", "yes"]])
    with pytest.raises(SheetStructureError, match="Draft Status"):
        source.read_pending_registrations()


def test_an_empty_sheet_yields_nothing():
    source, _ = make_source([])
    assert source.read_pending_registrations() == []


def test_the_marker_is_written_with_user_entered_formatting():
    source, values = make_source([HEADERS, ["2026-08-20", "Ann", "a@b.com", "yes", ""]])
    source.read_pending_registrations()
    source.mark_processed(2, "processed 2026-08-27", "draft-1")

    update = values.updates[0]
    assert update["range"] == "'Form responses 1'!E2"
    assert update["valueInputOption"] == "USER_ENTERED"
    assert update["body"] == {"values": [["processed 2026-08-27"]]}
    # The Timestamp cell is never touched, unlike the n8n update-by-match node.
    assert "Timestamp" not in str(update["body"])


def test_a_row_cannot_be_marked_without_a_draft_id():
    source, values = make_source([HEADERS, ["2026-08-20", "Ann", "a@b.com", "yes", ""]])
    source.read_pending_registrations()
    with pytest.raises(ValueError, match="without a draft id"):
        source.mark_processed(2, "processed 2026-08-27", "")
    assert values.updates == []


def test_marking_before_reading_is_refused():
    source, _ = make_source([HEADERS])
    with pytest.raises(SheetStructureError, match="before read_pending_registrations"):
        source.mark_processed(2, "processed 2026-08-27", "draft-1")
