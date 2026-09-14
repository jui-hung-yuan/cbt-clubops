"""How the public relay talks to the private service.

The relay holds no credential that can create anything. It proves who it is with
a token minted for it by Cloud Run, and the rules about that token are the kind
that fail with a 401 indistinguishable from a missing IAM binding — so they are
pinned here.
"""

from __future__ import annotations

from unittest import mock

import httpx
import pytest

from clubops.integrations.run_invoker import (
    InvocationError,
    MembershipServiceClient,
    fetch_id_token,
)

BASE = "https://cbt-membership-agent-xyz.a.run.app"


class FakeResponse:
    def __init__(self, *, text="", payload=None, status_code=200):
        self.text = text
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_the_token_is_minted_for_the_base_url_not_the_route():
    """Cloud Run compares the audience to the service URL. A token minted for
    the full path is rejected, and the error looks like an IAM problem."""
    with mock.patch(
        "httpx.get", return_value=FakeResponse(text="a.jwt.token\n")
    ) as get:
        assert fetch_id_token(BASE) == "a.jwt.token"

    assert get.call_args.kwargs["params"]["audience"] == BASE
    assert get.call_args.kwargs["headers"]["Metadata-Flavor"] == "Google"


def test_no_metadata_server_says_where_this_actually_works():
    """Off Cloud Run the failure is a connection error several layers down."""
    with mock.patch("httpx.get", side_effect=httpx.ConnectError("no route")):
        with pytest.raises(InvocationError, match="only works on Cloud Run"):
            fetch_id_token(BASE)


def test_a_successful_call_returns_the_private_services_answer():
    created = {"document_id": "abc", "link": "https://x", "dry_run": "false"}
    with mock.patch("httpx.get", return_value=FakeResponse(text="jwt")):
        with mock.patch(
            "httpx.post", return_value=FakeResponse(payload=created)
        ) as post:
            result = MembershipServiceClient(BASE).create_application_document(
                "Ada Lovelace", "ada@example.com"
            )

    assert result == created
    assert post.call_args[0][0] == f"{BASE}/jobs/application-document"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer jwt"
    assert post.call_args.kwargs["json"] == {
        "name": "Ada Lovelace",
        "email": "ada@example.com",
    }


def test_a_trailing_slash_does_not_become_a_double_slash():
    """Cloud Run does not route //jobs/..., and the 404 is baffling."""
    assert MembershipServiceClient(BASE + "/")._base_url == BASE


def test_a_403_names_the_missing_binding():
    with mock.patch("httpx.get", return_value=FakeResponse(text="jwt")):
        with mock.patch("httpx.post", return_value=FakeResponse(status_code=403)):
            with pytest.raises(InvocationError, match=r"run\.invoker"):
                MembershipServiceClient(BASE).create_application_document("A", "a@b.c")


def test_another_error_carries_the_private_services_own_message():
    with mock.patch("httpx.get", return_value=FakeResponse(text="jwt")):
        with mock.patch(
            "httpx.post",
            return_value=FakeResponse(status_code=500, text="PANDADOC_API_KEY missing"),
        ):
            with pytest.raises(InvocationError, match="PANDADOC_API_KEY missing"):
                MembershipServiceClient(BASE).create_application_document("A", "a@b.c")
