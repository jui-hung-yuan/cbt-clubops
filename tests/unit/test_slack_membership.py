"""Channel membership as the access-control list.

The point of this design is that the board manages access in Slack rather than
in an environment variable, so these tests are about the failure modes of asking
Slack the question.
"""

from __future__ import annotations

from unittest import mock

import pytest

from clubops.integrations.slack import (
    SlackChannelMembership,
    SlackError,
    post_deferred_reply,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_a_member_of_the_channel_is_allowed():
    membership = SlackChannelMembership("xoxb-x", "C1")
    with mock.patch(
        "httpx.get", return_value=FakeResponse({"ok": True, "members": ["U1", "U2"]})
    ):
        assert membership.allows("U1", now=0.0) is True
        assert membership.allows("U9", now=0.0) is False


def test_the_answer_is_cached_so_a_burst_is_one_api_call():
    membership = SlackChannelMembership("xoxb-x", "C1", cache_seconds=60)
    with mock.patch(
        "httpx.get", return_value=FakeResponse({"ok": True, "members": ["U1"]})
    ) as get:
        membership.allows("U1", now=0.0)
        membership.allows("U1", now=30.0)
        assert get.call_count == 1

        # ...and refreshed once it is stale, so removing an officer takes effect.
        membership.allows("U1", now=61.0)
        assert get.call_count == 2


def test_every_page_of_members_is_read():
    """A channel over one page would otherwise deny everyone past the first 200,
    which reads exactly like a broken token."""
    pages = [
        FakeResponse(
            {
                "ok": True,
                "members": ["U1"],
                "response_metadata": {"next_cursor": "more"},
            }
        ),
        FakeResponse({"ok": True, "members": ["U2"], "response_metadata": {}}),
    ]
    membership = SlackChannelMembership("xoxb-x", "C1")
    with mock.patch("httpx.get", side_effect=pages):
        assert membership.allows("U2", now=0.0) is True


def test_a_bot_outside_the_channel_says_so_in_words():
    membership = SlackChannelMembership("xoxb-x", "C1")
    with mock.patch(
        "httpx.get", return_value=FakeResponse({"ok": False, "error": "not_in_channel"})
    ):
        with pytest.raises(SlackError, match="/invite"):
            membership.allows("U1", now=0.0)


def test_a_missing_scope_names_the_scope():
    """`missing_scope` on a private channel means groups:read, which is not
    obvious from the error and costs an afternoon otherwise."""
    membership = SlackChannelMembership("xoxb-x", "C1")
    with mock.patch(
        "httpx.get", return_value=FakeResponse({"ok": False, "error": "missing_scope"})
    ):
        with pytest.raises(SlackError, match="groups:read"):
            membership.allows("U1", now=0.0)


def test_the_deferred_reply_is_posted_in_channel():
    """in_channel, not ephemeral: who created which document is worth recording
    where the rest of the board can see it."""
    with mock.patch("httpx.post", return_value=FakeResponse({"ok": True})) as post:
        post_deferred_reply("https://hooks.slack.com/x", "done")

    assert post.call_args.kwargs["json"]["response_type"] == "in_channel"
    assert post.call_args.kwargs["json"]["text"] == "done"
