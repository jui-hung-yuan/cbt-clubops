"""Slack adapter — posts to the membership admin channel.

Uses chat.postMessage directly rather than a client library; one call with one
dependency already in the tree is not worth another package.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


class SlackError(RuntimeError):
    """Raised when Slack rejects a post."""


class SlackNotifier:
    """Posts messages to a single channel, addressed by name (e.g. #channel)."""

    def __init__(self, bot_token: str, channel: str, timeout: float = 10.0) -> None:
        self._token = bot_token
        self._channel = channel
        self._timeout = timeout

    def post(self, text: str) -> None:
        response = httpx.post(
            POST_MESSAGE_URL,
            headers={"Authorization": f"Bearer {self._token}"},
            json={"channel": self._channel, "text": text, "mrkdwn": True},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            error = payload.get("error", "unknown_error")
            hint = ""
            if error == "not_in_channel":
                # This one reads like a token problem and is not: the bot has to
                # be invited to the channel with /invite.
                hint = f" — invite the bot to {self._channel} with /invite"
            raise SlackError(f"Slack rejected the message: {error}{hint}")
        logger.info("posted to %s", self._channel)


CONVERSATIONS_MEMBERS_URL = "https://slack.com/api/conversations.members"


class SlackChannelMembership:
    """Answers "is this Slack user in the admin channel?".

    This is the authorisation rule for the slash command, and it is deliberately
    not a list in an environment variable. The board already manages who belongs
    in ``#cbt-clubops-admin``; making that the ACL means adding an incoming
    officer is an invite and removing one is a kick, with no deploy and no second
    list to forget about. Keep the channel private, or membership means nothing.

    The result is cached briefly: a slash command is rare, but Slack retries and
    a burst of them should not become a burst of API calls.
    """

    def __init__(
        self,
        bot_token: str,
        channel_id: str,
        timeout: float = 10.0,
        cache_seconds: float = 60.0,
    ) -> None:
        self._token = bot_token
        self._channel_id = channel_id
        self._timeout = timeout
        self._cache_seconds = cache_seconds
        self._members: frozenset[str] = frozenset()
        self._fetched_at = 0.0

    def _fetch(self) -> frozenset[str]:
        members: list[str] = []
        cursor = ""
        # Paginated: a channel over 100 members returns a cursor, and ignoring it
        # would silently deny everyone past the first page.
        while True:
            params = {"channel": self._channel_id, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            response = httpx.get(
                CONVERSATIONS_MEMBERS_URL,
                headers={"Authorization": f"Bearer {self._token}"},
                params=params,
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                error = payload.get("error", "unknown_error")
                hint = ""
                if error == "not_in_channel":
                    hint = " — invite the bot to the admin channel with /invite"
                elif error == "missing_scope":
                    hint = " — the bot token needs groups:read (private channel)"
                raise SlackError(f"Slack rejected the members lookup: {error}{hint}")
            members.extend(payload.get("members", []))
            cursor = (payload.get("response_metadata") or {}).get("next_cursor", "")
            if not cursor:
                return frozenset(members)

    def allows(self, user_id: str, now: float) -> bool:
        """Whether that Slack user id is currently in the channel.

        ``now`` is passed in so the cache expiry is testable without sleeping.
        """
        if not self._members or now - self._fetched_at > self._cache_seconds:
            self._members = self._fetch()
            self._fetched_at = now
        return user_id in self._members


def post_deferred_reply(response_url: str, text: str, timeout: float = 10.0) -> None:
    """Send the real answer after the three-second ack.

    Slack gives every slash command a one-shot ``response_url``, valid for about
    thirty minutes, precisely for work that outlives the ack. ``in_channel``
    rather than the default ``ephemeral`` so the result is visible to the whole
    admin channel — the record of who created which document is worth more than
    the tidiness of a private reply.
    """
    response = httpx.post(
        response_url,
        json={"response_type": "in_channel", "text": text},
        timeout=timeout,
    )
    response.raise_for_status()
    logger.info("posted deferred reply")
