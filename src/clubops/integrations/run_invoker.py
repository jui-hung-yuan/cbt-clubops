"""Calls the private membership service from the public Slack relay.

The two-service split is the whole point of this module. The relay is reachable
from the internet because Slack has to reach it; the service holding the club's
Gmail refresh token and the PandaDoc key is not. The relay therefore holds no
credential that can create anything — it authenticates to the private service
the same way Cloud Scheduler already does, with a Google-minted ID token, and
that token is issued to its *identity*, not stored anywhere.

The token comes from Cloud Run's metadata server rather than from
``google.oauth2.id_token``: one HTTP call with a dependency already in the tree,
and it makes the audience rule (below) explicit instead of buried in a library.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

METADATA_IDENTITY_URL = (
    "http://metadata.google.internal/computeMetadata/v1/"
    "instance/service-accounts/default/identity"
)


class InvocationError(RuntimeError):
    """Raised when the private service could not be reached or refused."""


def fetch_id_token(audience: str, timeout: float = 10.0) -> str:
    """Mint an ID token for ``audience`` using the runtime's own identity.

    The audience must be the private service's **base URL**, with no path. Cloud
    Run compares it to the URL it serves; a token minted for
    ``.../jobs/application-document`` is rejected with a 401 that looks exactly
    like a missing IAM binding and is not one.
    """
    try:
        response = httpx.get(
            METADATA_IDENTITY_URL,
            params={"audience": audience},
            headers={"Metadata-Flavor": "Google"},
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        # Off Cloud Run there is no metadata server at all, and the failure is a
        # connection error several layers down. Name it here instead.
        raise InvocationError(
            f"could not mint an ID token for {audience}: {exc}. "
            "This only works on Cloud Run; locally, call the private service "
            "directly with scripts/create_application_doc.py"
        ) from exc
    return response.text.strip()


class MembershipServiceClient:
    """The private service, as seen from the relay."""

    def __init__(self, base_url: str, timeout: float = 300.0) -> None:
        # Trailing slashes turn into "//jobs/..." which Cloud Run does not route.
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def create_application_document(
        self, guest_name: str, guest_email: str
    ) -> dict[str, str]:
        """Ask the private service for one PandaDoc draft. Returns its response."""
        token = fetch_id_token(self._base_url)
        response = httpx.post(
            f"{self._base_url}/jobs/application-document",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": guest_name, "email": guest_email},
            timeout=self._timeout,
        )
        if response.status_code == 403:
            raise InvocationError(
                "the private service refused the relay's identity — grant it "
                "roles/run.invoker on cbt-clubops"
            )
        if response.status_code >= 400:
            raise InvocationError(
                f"the private service returned {response.status_code}: "
                f"{response.text[:400]}"
            )
        return response.json()
