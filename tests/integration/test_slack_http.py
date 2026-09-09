"""The public Slack endpoint.

This is the one route in the system reachable without IAM, so the tests are
mostly about what it refuses. The private service is never contacted; the client
that would call it is replaced.
"""

from __future__ import annotations

import time
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from clubops import slack_web
from clubops.config import RelaySettings
from clubops.domain.slack_command import expected_signature

SECRET = "8f742231b10e8888abcd99yyyzzz85a5"
BOARD_MEMBER = "U_BOARD"
OUTSIDER = "U_GUEST"

SETTINGS = RelaySettings(
    signing_secret=SECRET,
    bot_token="xoxb-test",
    admin_channel_id="C0123456789",
    core_service_url="https://cbt-clubops-xyz.a.run.app",
)


class FakeMembership:
    """The admin channel, as an ACL."""

    def __init__(self, members: set[str]) -> None:
        self.members = members

    def allows(self, user_id: str, now: float) -> bool:
        return user_id in self.members


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(slack_web, "_settings", lambda: SETTINGS)
    monkeypatch.setattr(
        slack_web, "_membership", lambda: FakeMembership({BOARD_MEMBER})
    )
    return TestClient(slack_web.app)


def _post(client, *, text="Ada Lovelace ada@example.com", user_id=BOARD_MEMBER,
          sign=True, timestamp=None):
    body = "&".join(
        [
            f"user_id={user_id}",
            "user_name=jui",
            "channel_id=C0123456789",
            "response_url=https://hooks.slack.com/commands/1/2/3",
            f"text={text.replace(' ', '+').replace('@', '%40')}",
        ]
    )
    stamp = timestamp or str(int(time.time()))
    signature = expected_signature(SECRET, stamp, body) if sign else "v0=deadbeef"
    return client.post(
        "/slack/commands/application-doc",
        content=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Slack-Request-Timestamp": stamp,
            "X-Slack-Signature": signature,
        },
    )


def test_healthcheck_reports_ok(client):
    assert client.get("/healthcheck").json() == {"status": "ok"}


def test_an_unsigned_request_gets_401_and_no_explanation(client):
    """Whoever found the URL is not a user to be helped."""
    with mock.patch.object(slack_web, "_create_and_report") as work:
        response = _post(client, sign=False)

    assert response.status_code == 401
    assert response.text == ""
    work.assert_not_called()


def test_a_replayed_request_is_refused_even_though_it_is_signed(client):
    old = str(int(time.time()) - 3600)
    with mock.patch.object(slack_web, "_create_and_report") as work:
        response = _post(client, timestamp=old)

    assert response.status_code == 401
    work.assert_not_called()


def test_someone_outside_the_admin_channel_is_refused(client):
    """A slash command is workspace-wide once installed, so the channel is the
    only thing standing between the workspace and a PandaDoc document."""
    with mock.patch.object(slack_web, "_create_and_report") as work:
        response = _post(client, user_id=OUTSIDER)

    assert response.status_code == 200
    assert "admin channel" in response.json()["text"]
    assert response.json()["response_type"] == "ephemeral"
    work.assert_not_called()


def test_a_typo_gets_a_usage_hint_rather_than_a_document(client):
    with mock.patch.object(slack_web, "_create_and_report") as work:
        response = _post(client, text="Ada Lovelace")

    assert response.status_code == 200
    assert "Usage" in response.json()["text"]
    work.assert_not_called()


def test_a_valid_command_acks_immediately_and_defers_the_work(client):
    """Slack gives the route three seconds; creating the document takes longer,
    so the answer the board sees first is only an acknowledgement."""
    with mock.patch.object(slack_web, "_create_and_report") as work:
        response = _post(client)

    assert response.status_code == 200
    assert "Creating the application document" in response.json()["text"]
    work.assert_called_once()
    assert work.call_args.kwargs["guest_name"] == "Ada Lovelace"
    assert work.call_args.kwargs["guest_email"] == "ada@example.com"


def test_the_deferred_reply_carries_the_link(monkeypatch):
    created = {
        "document_id": "abc",
        "link": "https://app.pandadoc.com/a/#/documents/abc",
        "name": "CBT Membership Application - Ada Lovelace",
        "dry_run": "false",
    }
    posted: list[tuple[str, str]] = []
    monkeypatch.setattr(
        slack_web, "post_deferred_reply", lambda url, text: posted.append((url, text))
    )
    monkeypatch.setattr(
        slack_web.MembershipServiceClient,
        "create_application_document",
        lambda self, name, email: created,
    )

    slack_web._create_and_report(
        base_url="https://private.example",
        response_url="https://hooks.slack.com/x",
        guest_name="Ada Lovelace",
        guest_email="ada@example.com",
        requested_by="jui",
    )

    assert len(posted) == 1
    assert created["link"] in posted[0][1]
    assert "draft" in posted[0][1]


def test_a_failure_is_reported_into_the_channel_rather_than_lost(monkeypatch):
    """Nothing is waiting to catch an exception from a background task, so a
    failure that is not posted is a failure nobody ever learns about."""
    posted: list[str] = []
    monkeypatch.setattr(
        slack_web, "post_deferred_reply", lambda url, text: posted.append(text)
    )
    monkeypatch.setattr(
        slack_web.MembershipServiceClient,
        "create_application_document",
        mock.Mock(side_effect=RuntimeError("PandaDoc said no")),
    )

    slack_web._create_and_report(
        base_url="https://private.example",
        response_url="https://hooks.slack.com/x",
        guest_name="Ada Lovelace",
        guest_email="ada@example.com",
        requested_by="jui",
    )

    assert len(posted) == 1
    assert "PandaDoc said no" in posted[0]
