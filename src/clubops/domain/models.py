"""Value types shared across the domain layer.

Everything here is immutable and free of I/O. Nothing in ``domain`` may import
from ``integrations`` or from ``google.adk`` — ``tests/test_boundaries.py``
enforces that.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CivilDate:
    """A calendar date with no time and no zone.

    Registrations are reasoned about in Europe/Berlin civil time. Carrying a
    bare (year, month, day) avoids the class of bug where a UTC instant lands
    on the previous day and shifts a guest's quote by a whole month.
    """

    year: int
    month: int
    day: int

    @property
    def iso(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"


@dataclass(frozen=True, slots=True)
class FeeConfig:
    """The club's published rates. Parameters, not constants — the 2026 rates
    are defaults, and changing them must never require editing the logic."""

    standard_monthly_fee: float = 21.0
    reduced_monthly_fee: float = 14.5
    application_fee: float = 25.0
    # Registrations on or before this day of the month start in the current
    # month; later ones start next month.
    current_month_cutoff_day: int = 10


DEFAULT_FEE_CONFIG = FeeConfig()


@dataclass(frozen=True, slots=True)
class ClubDetails:
    """Who the letter is from, and where the money goes.

    Configuration rather than constants, for two reasons. The obvious one is
    that officers change: a new VP Membership or a new treasurer must be an
    environment change, not a code change.

    The other is that these are a named person's bank account and a named
    person's signature — personal data, and this repository is public. The
    defaults below are deliberate placeholders, so a fresh clone builds, renders
    and passes its tests without ever holding anyone's details. Real values are
    supplied at deploy time; see docs/RUNBOOK.md.
    """

    bank_iban: str = "DE00 0000 0000 0000 0000 00"
    bank_bic: str = "XXXXDEXXXXX"
    bank_name: str = "EXAMPLE BANK"
    bank_owner: str = "Club Treasurer"
    signature_name: str = "The VP Membership"


DEFAULT_CLUB_DETAILS = ClubDetails()


@dataclass(frozen=True, slots=True)
class Quote:
    """The full fee breakdown for one guest.

    Every intermediate value is kept so the Slack message can show its working,
    exactly as the n8n Code node returned it.
    """

    start_year: int
    start_month: int
    start_month_name: str
    months: int
    period: str
    shifted: bool
    standard_monthly_fee: float
    reduced_monthly_fee: float
    application_fee: float
    membership_fee_standard: float
    membership_fee_reduced: float
    total_standard: float
    total_reduced: float
    calculation_line: str


@dataclass(frozen=True, slots=True)
class Registration:
    """One guest row as read from the sheet.

    ``row_number`` is the 1-based sheet row, captured during the read so the
    processed marker can be written back to that exact cell rather than by
    matching on the Timestamp value.
    """

    row_number: int
    timestamp_raw: str
    guest_name: str
    guest_email: str


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    body_html: str
