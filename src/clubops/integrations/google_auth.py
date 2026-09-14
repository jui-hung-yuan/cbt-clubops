"""Google credentials from a stored refresh token.

One OAuth identity serves both Sheets and Gmail, mirroring the n8n setup. The
OAuth client itself lives in the CBT account's Google Cloud project; the token
it mints is independent of the project this service runs in.
"""

from __future__ import annotations

import logging

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from clubops.config import GoogleCredentialsConfig

logger = logging.getLogger(__name__)

TOKEN_URI = "https://oauth2.googleapis.com/token"
TOKENINFO_URI = "https://oauth2.googleapis.com/tokeninfo"


class ScopeError(RuntimeError):
    """Raised when the token carries scopes we did not ask for."""


def build_credentials(
    config: GoogleCredentialsConfig, scopes: tuple[str, ...]
) -> Credentials:
    """Build refreshable user credentials and obtain an access token."""
    credentials = Credentials(
        token=None,
        refresh_token=config.refresh_token,
        client_id=config.client_id,
        client_secret=config.client_secret,
        token_uri=TOKEN_URI,
        scopes=list(scopes),
    )
    credentials.refresh(Request())
    return credentials


def assert_granted_scopes(credentials: Credentials, expected: tuple[str, ...]) -> None:
    """Fail fast if the token grants more than the workflow needs.

    This is the real guard behind "it drafts, it never sends". The
    ``gmail.compose`` scope is documented by Google as "Manage drafts and send
    emails" — it *does* permit sending — so the safety property cannot come from
    the scope alone. It comes from a Gmail client with no send code path
    (integrations/gmail.py) plus this check, which catches a token that was
    re-minted with a broader scope such as ``gmail.send`` or ``mail.google.com``.
    """
    response = httpx.get(
        TOKENINFO_URI, params={"access_token": credentials.token}, timeout=10.0
    )
    response.raise_for_status()
    granted = set(response.json().get("scope", "").split())

    unexpected = granted - set(expected)
    if unexpected:
        raise ScopeError(
            "refresh token grants unexpected scopes: "
            f"{sorted(unexpected)}. Re-mint it with exactly {list(expected)}."
        )

    missing = set(expected) - granted
    if missing:
        raise ScopeError(f"refresh token is missing required scopes: {sorted(missing)}")

    logger.info("token scopes verified: %s", sorted(granted))
