"""The rules that make a public endpoint safe, and the ones that make it usable.

Every case here runs without a Slack workspace, which is the point: the relay's
authentication is a hash, so it can be checked exactly.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from clubops.domain.slack_command import (
    MAX_REQUEST_AGE_SECONDS,
    CommandUsageError,
    SlackSignatureError,
    expected_signature,
    parse_application_command,
    verify_signature,
)

SECRET = "8f742231b10e8888abcd99yyyzzz85a5"
BODY = "token=x&team_id=T1&user_id=U123&text=Ada+Lovelace+ada%40example.com"
NOW = 1_700_000_000.0


def _signed(timestamp: str = "1700000000", body: str = BODY) -> str:
    return expected_signature(SECRET, timestamp, body)


def test_a_correctly_signed_request_is_accepted():
    verify_signature(
        signing_secret=SECRET,
        timestamp="1700000000",
        body=BODY,
        signature=_signed(),
        now=NOW,
    )


def test_the_signature_is_the_documented_hmac():
    """Pinned against the algorithm itself rather than against our own helper,
    so a refactor cannot quietly redefine what "valid" means."""
    base = f"v0:1700000000:{BODY}".encode()
    digest = hmac.new(SECRET.encode(), base, hashlib.sha256).hexdigest()
    assert expected_signature(SECRET, "1700000000", BODY) == f"v0={digest}"


def test_a_tampered_body_is_rejected():
    """The body is signed, so changing the guest's address invalidates it —
    which is what stops a valid request being edited in flight."""
    with pytest.raises(SlackSignatureError):
        verify_signature(
            signing_secret=SECRET,
            timestamp="1700000000",
            body=BODY.replace("ada", "eve"),
            signature=_signed(),
            now=NOW,
        )


def test_a_wrong_secret_is_rejected():
    with pytest.raises(SlackSignatureError):
        verify_signature(
            signing_secret=SECRET,
            timestamp="1700000000",
            body=BODY,
            signature=expected_signature("not-the-secret", "1700000000", BODY),
            now=NOW,
        )


def test_an_old_request_is_rejected_even_though_its_signature_is_valid():
    """A captured request stays perfectly signed forever. The expiry window is
    the only thing that makes replaying it useless."""
    with pytest.raises(SlackSignatureError, match="replay window"):
        verify_signature(
            signing_secret=SECRET,
            timestamp="1700000000",
            body=BODY,
            signature=_signed(),
            now=NOW + MAX_REQUEST_AGE_SECONDS + 1,
        )


def test_a_request_from_the_future_is_rejected_too():
    with pytest.raises(SlackSignatureError, match="replay window"):
        verify_signature(
            signing_secret=SECRET,
            timestamp="1700000000",
            body=BODY,
            signature=_signed(),
            now=NOW - MAX_REQUEST_AGE_SECONDS - 1,
        )


@pytest.mark.parametrize("timestamp", ["", "not-a-number", None])
def test_an_unreadable_timestamp_is_rejected(timestamp):
    with pytest.raises(SlackSignatureError):
        verify_signature(
            signing_secret=SECRET,
            timestamp=timestamp,
            body=BODY,
            signature=_signed(),
            now=NOW,
        )


def test_an_empty_signing_secret_fails_closed():
    """A blank secret must not mean "anything verifies": an unset environment
    variable would otherwise authenticate the whole internet."""
    with pytest.raises(SlackSignatureError, match="signing secret"):
        verify_signature(
            signing_secret="",
            timestamp="1700000000",
            body=BODY,
            signature=expected_signature("", "1700000000", BODY),
            now=NOW,
        )


@pytest.mark.parametrize(
    ("text", "name", "email"),
    [
        ("Ada Lovelace ada@example.com", "Ada Lovelace", "ada@example.com"),
        ("Ada ada@example.com", "Ada", "ada@example.com"),
        (
            "Ada King de Lovelace ada@example.co.uk",
            "Ada King de Lovelace",
            "ada@example.co.uk",
        ),
        ("  Ada Lovelace   ada@example.com  ", "Ada Lovelace", "ada@example.com"),
        # Slack turns a typed address into a link before we ever see it.
        (
            "Ada Lovelace <mailto:ada@example.com|ada@example.com>",
            "Ada Lovelace",
            "ada@example.com",
        ),
        ("Ada Lovelace <mailto:ada@example.com>", "Ada Lovelace", "ada@example.com"),
    ],
)
def test_the_command_text_splits_into_a_name_and_an_email(text, name, email):
    assert parse_application_command(text) == (name, email)


@pytest.mark.parametrize(
    "text", ["", "   ", "Ada Lovelace", "ada@example.com", "Ada ada@example"]
)
def test_unusable_command_text_asks_for_the_right_shape(text):
    with pytest.raises(CommandUsageError, match="application-doc"):
        parse_application_command(text)
