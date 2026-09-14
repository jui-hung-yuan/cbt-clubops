"""Draft construction, and the guarantee that this module cannot send."""

from __future__ import annotations

import base64
from email import message_from_bytes
from pathlib import Path

import pytest

from clubops.integrations import gmail
from clubops.integrations.gmail import GmailDraftCreator, build_raw_message


def decode(raw: str):
    return message_from_bytes(base64.urlsafe_b64decode(raw))


def test_the_message_carries_the_recipient_and_subject():
    message = decode(build_raw_message("guest@example.com", "Hello", "<p>Hi</p>"))
    assert message["To"] == "guest@example.com"
    assert message["Subject"] == "Hello"


def test_the_body_is_sent_as_html_not_plain_text():
    """n8n used Email Type = HTML; plain text would show the guest raw tags."""
    message = decode(build_raw_message("g@example.com", "S", "<p>Hi <b>there</b></p>"))
    assert message.get_content_type() == "text/html"
    assert "<b>there</b>" in message.get_payload(decode=True).decode()


def test_non_ascii_content_survives_the_round_trip():
    message = decode(
        build_raw_message("g@example.com", "S", "<p>&euro; 14,50 — ok</p>")
    )
    assert "—" in message.get_payload(decode=True).decode()


class FakeDrafts:
    def __init__(self, result):
        self._result = result
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def execute(self):
        return self._result


class FakeService:
    def __init__(self, drafts):
        self._drafts = drafts

    def users(self):
        return self

    def drafts(self):
        return self._drafts


def test_creating_a_draft_returns_its_id():
    drafts = FakeDrafts({"id": "r-123"})
    creator = GmailDraftCreator(FakeService(drafts))
    assert creator.create_draft("g@example.com", "S", "<p>B</p>") == "r-123"
    assert drafts.calls[0]["userId"] == "me"


def test_a_draft_without_a_recipient_is_refused():
    creator = GmailDraftCreator(FakeService(FakeDrafts({"id": "x"})))
    with pytest.raises(ValueError, match="without a recipient"):
        creator.create_draft("   ", "S", "<p>B</p>")


def test_a_response_without_an_id_is_an_error():
    creator = GmailDraftCreator(FakeService(FakeDrafts({})))
    with pytest.raises(RuntimeError, match="no draft id"):
        creator.create_draft("g@example.com", "S", "<p>B</p>")


def test_the_module_has_no_send_code_path():
    """The workflow drafts and never sends.

    The gmail.compose scope does NOT enforce this — Google documents it as
    "Manage drafts and send emails". The guarantee is that no send call exists
    in the code, which is what this asserts.
    """
    source = Path(gmail.__file__).read_text()
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    # Strip the module docstring, which names the endpoints it refuses to call.
    body = code.split('"""', 2)[-1]
    assert ".send(" not in body
    assert "messages().send" not in body
    assert "drafts().send" not in body
