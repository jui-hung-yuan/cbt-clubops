"""The interfaces the pipeline depends on.

This is the seam. ``pipeline.py`` is written against these protocols, never
against ``googleapiclient`` or Slack's HTTP API, so a Google Workspace MCP
server (or an agent tool, or a test fake) can be substituted without
touching the workflow logic.
"""

from __future__ import annotations

from typing import Protocol

from clubops.domain.models import Registration


class RegistrationSource(Protocol):
    """Where guest registrations come from, and where progress is recorded."""

    def read_pending_registrations(self) -> list[Registration]:
        """Rows with no Draft Status and a non-empty email address."""
        ...

    def mark_processed(self, row_number: int, marker: str, draft_id: str) -> None:
        """Write the processed marker to that row's Draft Status cell.

        ``draft_id`` is required so this cannot be called before a draft exists.
        The ordering guarantee is enforced by the signature, not by convention.
        """
        ...


class DraftCreator(Protocol):
    """Creates a mail draft for human review. Never sends."""

    def create_draft(self, to: str, subject: str, body_html: str) -> str:
        """Return the created draft's id."""
        ...


class Notifier(Protocol):
    """Posts a message to the membership admin channel."""

    def post(self, text: str) -> None: ...
