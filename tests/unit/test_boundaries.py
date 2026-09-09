"""The domain layer must stay free of I/O and of agent frameworks.

This is the property that lets Phase 2 wrap the same functions as agent tools,
and Phase 4 expose them over MCP, without touching the business logic. It is
enforced here rather than left to discipline.
"""

import ast
from pathlib import Path

import pytest

DOMAIN = Path(__file__).parent.parent.parent / "src" / "clubops" / "domain"

FORBIDDEN_PREFIXES = (
    "clubops.integrations",
    "google.adk",
    "googleapiclient",
    "google.auth",
    "google.oauth2",
    "fastapi",
    "httpx",
    "requests",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize("path", sorted(DOMAIN.glob("*.py")), ids=lambda p: p.name)
def test_domain_modules_import_no_io_or_frameworks(path):
    for module in _imported_modules(path):
        for forbidden in FORBIDDEN_PREFIXES:
            assert not module.startswith(forbidden), (
                f"{path.name} imports {module}; the domain layer must stay pure "
                f"so it can be reused by agent tools and MCP without change"
            )


SRC = Path(__file__).parent.parent.parent / "src" / "clubops"

# What the public service must not be able to reach. The Slack relay is the only
# thing on the internet; if it can import the code that talks to Gmail, Sheets or
# PandaDoc, then someone will eventually give it the credentials to go with them
# and the split will have quietly stopped being a split.
CREDENTIAL_BEARING = (
    "clubops.jobs",
    "clubops.pipeline",
    "clubops.integrations.gmail",
    "clubops.integrations.sheets",
    "clubops.integrations.pandadoc",
    "clubops.integrations.google_auth",
)


def test_the_slack_relay_cannot_reach_the_credential_bearing_code():
    """The public service talks to the private one over HTTP, never in-process.

    This is the property that makes the two-service split worth its second
    deploy: a compromise of the relay yields a Slack signing secret, not the
    club's mailbox.
    """
    for module in _imported_modules(SRC / "slack_web.py"):
        assert module not in CREDENTIAL_BEARING, (
            f"slack_web.py imports {module}; the public relay must reach the "
            f"private service over HTTP so it never holds its credentials"
        )


def test_the_relay_config_cannot_read_the_private_services_secrets():
    """``load_relay_settings`` is separate from ``load_settings`` on purpose: the
    relay should be unable to start with the Gmail refresh token in scope."""
    source = (SRC / "config.py").read_text()
    relay_section = source[source.index("def load_relay_settings") :]
    for forbidden in (
        "GOOGLE_OAUTH_REFRESH_TOKEN",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "PANDADOC_API_KEY",
        "SPREADSHEET_ID",
    ):
        assert forbidden not in relay_section, (
            f"load_relay_settings reads {forbidden}; the public relay must not "
            f"know that variable exists"
        )
