"""Slash-command parsing and Slack request authentication.

Pure: hashing and string handling only, so every rule below is testable without
a network and without a Slack workspace. The HTTP plumbing lives in
``slack_web.py``, the Slack API calls in ``integrations/slack.py``.

This module is what makes the public service safe to expose. Slack's endpoint
cannot be IAM-protected — Slack's servers cannot present a Google ID token — so
the proof that a request came from Slack is a shared-secret signature, checked
here before anything else happens.
"""

from __future__ import annotations

import hashlib
import hmac
import re

# Slack signs with this version prefix. It has never changed, but the value is
# part of the signed string, so it is spelled out rather than assumed.
SIGNATURE_VERSION = "v0"

# Slack's own recommendation. A captured request is replayable until it expires,
# so this is the width of the replay window, not a clock-skew allowance.
MAX_REQUEST_AGE_SECONDS = 60 * 5


class SlackSignatureError(Exception):
    """Raised when a request cannot be proven to have come from Slack."""


class CommandUsageError(Exception):
    """Raised when the text after the slash command is not a name and an email.

    Distinct from :class:`SlackSignatureError`: this one is a real board member
    making a typo, and the answer is a usage hint, not a 401.
    """


def expected_signature(signing_secret: str, timestamp: str, body: str) -> str:
    """The signature Slack should have sent for this exact request.

    The signed string is ``v0:{timestamp}:{body}`` and ``body`` is the raw bytes
    Slack sent, decoded — not a re-serialised form dict. Re-encoding reorders or
    re-escapes parameters and every signature then fails to match.
    """
    base = f"{SIGNATURE_VERSION}:{timestamp}:{body}"
    digest = hmac.new(
        signing_secret.encode("utf-8"), base.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"


def verify_signature(
    *,
    signing_secret: str,
    timestamp: str,
    body: str,
    signature: str,
    now: float,
) -> None:
    """Raise unless this request provably came from Slack, recently.

    ``now`` is passed in rather than read from the clock so the expiry rule can
    be tested at a fixed instant.
    """
    if not signing_secret:
        # A blank secret makes every signature verifiable by anyone who can read
        # the algorithm. Fail closed rather than authenticate the internet.
        raise SlackSignatureError("no signing secret is configured")

    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise SlackSignatureError("missing or unreadable timestamp") from exc

    if abs(now - sent_at) > MAX_REQUEST_AGE_SECONDS:
        raise SlackSignatureError("request is outside the replay window")

    expected = expected_signature(signing_secret, timestamp, body)
    # Constant time: a plain == returns sooner the earlier it finds a mismatched
    # byte, which is enough to recover a valid signature one byte at a time.
    if not hmac.compare_digest(expected, signature or ""):
        raise SlackSignatureError("signature does not match")


# Deliberately loose. This rejects "Ada Lovelace" and typos like "ada@example",
# not exotic-but-valid addresses; PandaDoc is the authority on deliverability.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

USAGE = "Usage: `/application-doc Ada Lovelace ada@example.com`"


def parse_application_command(text: str) -> tuple[str, str]:
    """Split ``"Ada Lovelace ada@example.com"`` into a name and an email.

    The email is taken as the last whitespace-separated token and everything
    before it is the name, so names with any number of parts work without the
    board having to learn a quoting convention.
    """
    parts = (text or "").split()
    if len(parts) < 2:
        raise CommandUsageError(USAGE)

    # Slack rewrites a typed address into a link before it reaches us:
    # "ada@example.com" arrives as "<mailto:ada@example.com|ada@example.com>".
    # Unwrapping it here means the board types an address and it just works.
    email = parts[-1].strip("<>")
    if "|" in email:
        email = email.split("|", 1)[1]
    email = email.removeprefix("mailto:")

    if not _EMAIL.match(email):
        raise CommandUsageError(f"{parts[-1]!r} is not an email address. {USAGE}")

    name = " ".join(parts[:-1]).strip()
    if not name:
        raise CommandUsageError(USAGE)

    return name, email
