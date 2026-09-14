"""Runtime configuration, entirely from the environment.

Secrets arrive as environment variables too: on Cloud Run they are mounted from
Secret Manager with ``--set-secrets``, so nothing here reaches out to a secret
API and local development only needs a ``.env`` file.

Settings are validated once at startup by :func:`load_settings`, which raises
rather than letting a missing spreadsheet ID surface as a confusing 404 at 23:00
on a Saturday.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from clubops.domain.models import (
    DEFAULT_CLUB_DETAILS,
    CivilDate,
    ClubDetails,
    FeeConfig,
)
from clubops.domain.timestamps import parse_timestamp

# The workflow drafts; it must never send. See integrations/gmail.py, which has
# no send code path, and asserts these are the only scopes actually granted.
REQUIRED_SCOPES = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.compose",
)


# The club address printed on the application form itself. The officer is the
# form's second required signature, so this needs no setup to be correct.
DEFAULT_OFFICER_EMAIL = "cb.toastmasters.d95@gmail.com"
DEFAULT_OFFICER_NAME = "Center Berlin Toastmasters"


class ConfigError(RuntimeError):
    """Raised when the environment cannot produce a usable configuration."""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"missing required environment variable: {name}")
    return value


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _number(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True, slots=True)
class GoogleCredentialsConfig:
    """One OAuth identity covers both Sheets and Gmail, as it did in n8n.

    A service account is not an option: the club mailbox is a consumer Gmail
    account, so domain-wide delegation is unavailable. The refresh token is
    minted once by scripts/mint_refresh_token.py.
    """

    client_id: str
    client_secret: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class PandaDocConfig:
    """Credentials and the fixed second signer for application documents.

    The officer is the club address printed on the form itself, so it needs no
    setup to work; the env var exists only so a different officer can sign
    without a redeploy.
    """

    api_key: str
    officer_email: str
    officer_name: str


@dataclass(frozen=True, slots=True)
class Settings:
    spreadsheet_id: str
    sheet_name: str
    process_rows_after: CivilDate
    date_order: str
    slack_channel: str
    slack_bot_token: str
    timezone: str
    google: GoogleCredentialsConfig
    pandadoc: PandaDocConfig
    fees: FeeConfig
    dry_run: bool
    service_name: str
    project_id: str
    scopes: tuple[str, ...] = field(default=REQUIRED_SCOPES)
    # Defaulted so a Settings built in a test carries the placeholders
    # rather than having to name someone's bank account.
    club: ClubDetails = DEFAULT_CLUB_DETAILS


def load_settings() -> Settings:
    """Build and validate settings from the environment."""
    date_order = os.getenv("DATE_ORDER", "DMY").strip().upper() or "DMY"
    if date_order not in {"DMY", "MDY"}:
        raise ConfigError(f"DATE_ORDER must be DMY or MDY, got {date_order!r}")

    raw_cutoff = _required("PROCESS_ROWS_AFTER")
    try:
        process_rows_after = parse_timestamp(raw_cutoff, date_order)
    except ValueError as exc:
        raise ConfigError(f"PROCESS_ROWS_AFTER is unparseable: {exc}") from exc

    cutoff_day = int(_number("CURRENT_MONTH_CUTOFF_DAY", 10))
    if not 1 <= cutoff_day <= 31:
        raise ConfigError(f"CURRENT_MONTH_CUTOFF_DAY out of range: {cutoff_day}")

    return Settings(
        spreadsheet_id=_required("SPREADSHEET_ID"),
        sheet_name=os.getenv("SHEET_NAME", "Form responses 1"),
        process_rows_after=process_rows_after,
        date_order=date_order,
        slack_channel=os.getenv("SLACK_CHANNEL", "#cbt-clubops-admin"),
        slack_bot_token=_required("SLACK_BOT_TOKEN"),
        timezone=os.getenv("TIMEZONE", "Europe/Berlin"),
        google=GoogleCredentialsConfig(
            client_id=_required("GOOGLE_OAUTH_CLIENT_ID"),
            client_secret=_required("GOOGLE_OAUTH_CLIENT_SECRET"),
            refresh_token=_required("GOOGLE_OAUTH_REFRESH_TOKEN"),
        ),
        pandadoc=PandaDocConfig(
            # Deliberately not _required: the twice-weekly email job calls
            # load_settings() too, and must keep running on a deployment that
            # has no PandaDoc key. The application-document job checks for it.
            api_key=os.getenv("PANDADOC_API_KEY", "").strip(),
            officer_email=os.getenv(
                "PANDADOC_OFFICER_EMAIL", DEFAULT_OFFICER_EMAIL
            ).strip(),
            officer_name=os.getenv(
                "PANDADOC_OFFICER_NAME", DEFAULT_OFFICER_NAME
            ).strip(),
        ),
        club=ClubDetails(
            # Unset means the placeholders in ClubDetails, which are obviously
            # not a real account. That is the safe failure: a guest who receives
            # one asks what it is, rather than paying the wrong person.
            **{
                field: value
                for field, env in (
                    ("bank_iban", "BANK_IBAN"),
                    ("bank_bic", "BANK_BIC"),
                    ("bank_name", "BANK_NAME"),
                    ("bank_owner", "BANK_OWNER"),
                    ("signature_name", "SIGNATURE_NAME"),
                )
                if (value := os.getenv(env, "").strip())
            }
        ),
        fees=FeeConfig(
            standard_monthly_fee=_number("STANDARD_MONTHLY_FEE", 21.0),
            reduced_monthly_fee=_number("REDUCED_MONTHLY_FEE", 14.5),
            application_fee=_number("APPLICATION_FEE", 25.0),
            current_month_cutoff_day=cutoff_day,
        ),
        dry_run=_flag("DRY_RUN", False),
        service_name=os.getenv("K_SERVICE", "cbt-clubops"),
        project_id=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
    )


@dataclass(frozen=True, slots=True)
class RelaySettings:
    """Configuration for the public Slack relay, and nothing else.

    Loaded by :func:`load_relay_settings`, which is deliberately *not*
    :func:`load_settings`. The relay is the internet-facing service; it must be
    unable to start with the club's Gmail refresh token or the PandaDoc key in
    its environment, and the cheapest way to guarantee that is for its
    configuration loader to have no idea those variables exist.

    ``core_service_url`` is the private service (``cbt-clubops``), which is the
    only thing this one is allowed to call.

    ``admin_channel_id`` is an id (``C...``/``G...``), not ``#name``:
    ``conversations.members`` takes only ids.
    """

    signing_secret: str
    bot_token: str
    admin_channel_id: str
    core_service_url: str


def load_relay_settings() -> RelaySettings:
    """Build and validate the relay's settings from the environment."""
    channel = _required("SLACK_ADMIN_CHANNEL_ID")
    if channel.startswith("#"):
        raise ConfigError(
            "SLACK_ADMIN_CHANNEL_ID must be a channel id like C0123456789, "
            f"not a name; got {channel!r}. Right-click the channel in Slack -> "
            "View channel details; the id is at the bottom."
        )
    return RelaySettings(
        signing_secret=_required("SLACK_SIGNING_SECRET"),
        bot_token=_required("SLACK_BOT_TOKEN"),
        admin_channel_id=channel,
        core_service_url=_required("CORE_SERVICE_URL").rstrip("/"),
    )
