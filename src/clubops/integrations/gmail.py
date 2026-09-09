"""Gmail adapter — creates drafts, and only drafts.

There is deliberately no method here that sends. ``users.messages.send`` and
``users.drafts.send`` do not appear anywhere in this module, so no bug elsewhere
in the service can reach them.

That matters more than it looks. The ``gmail.compose`` scope is documented by
Google as "Manage drafts and send emails" — it permits sending. The guarantee
that this workflow never sends is therefore enforced here, in code, and by the
scope assertion in ``google_auth.assert_granted_scopes`` — not by the scope.
"""

from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from typing import Any

logger = logging.getLogger(__name__)


def build_raw_message(to: str, subject: str, body_html: str) -> str:
    """Build a base64url-encoded RFC 2822 message with an HTML body."""
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    # n8n sent these with Email Type = HTML. Sending the same content as plain
    # text would show the recipient raw tags.
    message.set_content(body_html, subtype="html")
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


class GmailDraftCreator:
    """Creates a draft in the authenticated mailbox for a human to review."""

    def __init__(self, service: Any) -> None:
        self._drafts = service.users().drafts()

    def create_draft(self, to: str, subject: str, body_html: str) -> str:
        if not to.strip():
            raise ValueError("cannot create a draft without a recipient")
        created = self._drafts.create(
            userId="me",
            body={"message": {"raw": build_raw_message(to, subject, body_html)}},
        ).execute()
        draft_id = created.get("id")
        if not draft_id:
            raise RuntimeError(f"Gmail returned no draft id: {created!r}")
        logger.info("created draft %s for %s", draft_id, to)
        return str(draft_id)
