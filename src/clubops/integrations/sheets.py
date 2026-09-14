"""Google Sheets adapter — reading registrations and recording progress.

Columns are located by header name, not position, so a Google Form edit that
inserts a question and pushes ``Draft Status`` one column to the right does not
break the run.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from clubops.config import Settings
from clubops.domain.models import Registration

logger = logging.getLogger(__name__)

# Registrations arrive as displayed in the sheet, matching what n8n read with
# its default options. The Timestamp is therefore a locale-formatted string,
# which is why domain/timestamps.py parses it explicitly.
VALUE_RENDER_OPTION = "FORMATTED_VALUE"
# Matches the n8n node's cellFormat: USER_ENTERED.
VALUE_INPUT_OPTION = "USER_ENTERED"

# The first data row. Row 1 holds the headers.
FIRST_DATA_ROW = 2

# Column headers. Matched by name, not position, so a Google Form edit that
# inserts a question and pushes Draft Status one column right still works.
TIMESTAMP_COLUMN = "Timestamp"
NAME_COLUMN = "First and last name"
EMAIL_COLUMN = "Your email address"
DRAFT_STATUS_COLUMN = "Draft Status"


class SheetStructureError(RuntimeError):
    """Raised when the sheet is missing a column the workflow depends on."""


def column_letter(index: int) -> str:
    """0-based column index to an A1 column label (0 -> A, 26 -> AA)."""
    if index < 0:
        raise ValueError(f"column index must be non-negative, got {index}")
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def is_pending(
    row: Mapping[str, str], draft_status_column: str, email_column: str
) -> bool:
    """The n8n "Only Rows Without a Draft" filter: no draft status, has an email.

    Both tests are on the trimmed string, matching n8n's loose "is empty" /
    "is not empty" string operators.
    """
    has_no_draft = not str(row.get(draft_status_column, "") or "").strip()
    has_email = bool(str(row.get(email_column, "") or "").strip())
    return has_no_draft and has_email


class SheetsRegistrationSource:
    """Reads the guest registration sheet and writes the processed marker."""

    def __init__(self, service: Any, settings: Settings) -> None:
        self._values = service.spreadsheets().values()
        self._settings = settings
        self._draft_status_index: int | None = None

    def read_pending_registrations(self) -> list[Registration]:
        settings = self._settings
        response = self._values.get(
            spreadsheetId=settings.spreadsheet_id,
            range=f"'{settings.sheet_name}'",
            valueRenderOption=VALUE_RENDER_OPTION,
        ).execute()

        rows: Sequence[Sequence[str]] = response.get("values", [])
        if not rows:
            logger.info("sheet %s is empty", settings.sheet_name)
            return []

        headers = [str(h).strip() for h in rows[0]]
        if DRAFT_STATUS_COLUMN not in headers:
            raise SheetStructureError(
                f"the sheet has no {DRAFT_STATUS_COLUMN!r} column; "
                "add it as the last column before running"
            )
        self._draft_status_index = headers.index(DRAFT_STATUS_COLUMN)

        pending: list[Registration] = []
        for offset, raw_row in enumerate(rows[1:]):
            # Sheets truncates trailing empty cells, so pad before zipping.
            padded = list(raw_row) + [""] * (len(headers) - len(raw_row))
            record = dict(zip(headers, padded, strict=False))
            if not is_pending(record, DRAFT_STATUS_COLUMN, EMAIL_COLUMN):
                continue
            pending.append(
                Registration(
                    row_number=FIRST_DATA_ROW + offset,
                    timestamp_raw=str(record.get(TIMESTAMP_COLUMN, "")),
                    guest_name=str(record.get(NAME_COLUMN, "") or "").strip(),
                    guest_email=str(record.get(EMAIL_COLUMN, "") or "").strip(),
                )
            )

        logger.info("read %d rows, %d pending", max(len(rows) - 1, 0), len(pending))
        return pending

    def mark_processed(self, row_number: int, marker: str, draft_id: str) -> None:
        """Write the marker to this row's Draft Status cell.

        Targeting the row by index — rather than by matching on the Timestamp
        value, as n8n did — means duplicate timestamps cannot cause the wrong
        row to be marked, and the Timestamp cell is never rewritten.

        ``draft_id`` is required and checked: a row must never be marked
        processed unless the draft it refers to actually exists.
        """
        if not draft_id:
            raise ValueError(
                f"refusing to mark row {row_number} processed without a draft id"
            )
        if self._draft_status_index is None:
            raise SheetStructureError(
                "mark_processed called before read_pending_registrations; "
                "the Draft Status column position is not known yet"
            )
        cell = f"{column_letter(self._draft_status_index)}{row_number}"
        self._values.update(
            spreadsheetId=self._settings.spreadsheet_id,
            range=f"'{self._settings.sheet_name}'!{cell}",
            valueInputOption=VALUE_INPUT_OPTION,
            body={"values": [[marker]]},
        ).execute()
        logger.info("marked row %d as %r for draft %s", row_number, marker, draft_id)
