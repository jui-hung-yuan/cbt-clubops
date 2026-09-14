"""Parsing the sheet's Timestamp column.

A faithful port of ``parseTimestamp`` / ``toComparable`` from the "Calculate
Membership Fee" n8n Code node.

Google Sheets hands the Timestamp back as a locale-formatted string, so it is
parsed explicitly rather than by a general-purpose date parser. Where the
day/month order is genuinely ambiguous we fall back to ``date_order``; where one
component exceeds 12 we resolve it unambiguously and do.
"""

from __future__ import annotations

import re

from clubops.domain.models import CivilDate

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_SLASH = re.compile(r"^(\d{1,2})[/.](\d{1,2})[/.](\d{4})")

DateOrder = str  # "DMY" or "MDY"


def parse_timestamp(raw: object, date_order: DateOrder = "DMY") -> CivilDate:
    """Parse a sheet Timestamp into a civil date.

    Raises ``ValueError`` on empty or unrecognised input, so a bad row fails
    loudly for that guest rather than silently producing a wrong quote.
    """
    if raw is None or str(raw).strip() == "":
        raise ValueError(
            "Row has an empty Timestamp; cannot determine the entry month."
        )
    text = str(raw).strip()

    iso = _ISO.match(text)
    if iso:
        return CivilDate(int(iso[1]), int(iso[2]), int(iso[3]))

    slash = _SLASH.match(text)
    if slash:
        a, b, year = int(slash[1]), int(slash[2]), int(slash[3])
        if a > 12:
            day, month = a, b
        elif b > 12:
            day, month = b, a
        elif date_order == "DMY":
            day, month = a, b
        else:
            day, month = b, a
        return CivilDate(year, month, day)

    raise ValueError(f"Unrecognised Timestamp format: {text}")


def to_comparable(date: CivilDate) -> int:
    """Collapse a civil date to a sortable integer, for the cutoff comparison."""
    return date.year * 10000 + date.month * 100 + date.day


def is_before_cutoff(registered_on: CivilDate, cutoff: CivilDate) -> bool:
    """True when a registration predates the go-live cutoff and must be ignored.

    Rows older than the cutoff are skipped entirely, which is why historic rows
    never need a manual "processed" backfill.
    """
    return to_comparable(registered_on) < to_comparable(cutoff)
