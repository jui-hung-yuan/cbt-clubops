"""Test-wide isolation from the developer's own environment.

``web.py`` and ``slack_web.py`` call ``load_dotenv()`` at import, so importing
either one — as the HTTP tests do — reads the local ``.env`` into
``os.environ`` for the rest of the session. Without this, a test that reads
configuration passes or fails depending on what happens to be in the .env of
whoever is running it, and on some machines the real club bank details would be
the thing under test.

The suite's contract is "no network, no credentials". This enforces it.
"""

from __future__ import annotations

import pytest

# Everything config.py reads. Listed explicitly rather than matched by prefix so
# that adding a variable is a deliberate decision here too.
CONFIG_ENV = (
    "SPREADSHEET_ID",
    "SHEET_NAME",
    "PROCESS_ROWS_AFTER",
    "DATE_ORDER",
    "TIMEZONE",
    "SLACK_CHANNEL",
    "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_SECRET",
    "SLACK_ADMIN_CHANNEL_ID",
    "CORE_SERVICE_URL",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REFRESH_TOKEN",
    "GOOGLE_CLOUD_PROJECT",
    "PANDADOC_API_KEY",
    "PANDADOC_OFFICER_EMAIL",
    "PANDADOC_OFFICER_NAME",
    "STANDARD_MONTHLY_FEE",
    "REDUCED_MONTHLY_FEE",
    "APPLICATION_FEE",
    "CURRENT_MONTH_CUTOFF_DAY",
    "DRY_RUN",
    "BANK_IBAN",
    "BANK_BIC",
    "BANK_NAME",
    "BANK_OWNER",
    "SIGNATURE_NAME",
)


@pytest.fixture(autouse=True)
def _no_ambient_configuration(monkeypatch):
    """Start every test from an empty configuration.

    A test that wants a value sets it with ``monkeypatch.setenv``, which still
    works — this only removes what leaked in from the machine.
    """
    for name in CONFIG_ENV:
        monkeypatch.delenv(name, raising=False)
