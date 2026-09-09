"""Center Berlin Toastmasters — membership fee calculation.

Pure, dependency-free, no I/O.

Rules encoded here (source: assets/CBT_application_form_2026_fees_v2.pdf):
  - Two terms per year: April-September and October-March.
  - A member pays from their entry month to the end of the current term.
  - Exception: entry in September or March (the last month of a term) would mean
    paying for a single month, so they pay that month plus the entire next
    term = 7 months.
  - Standard rate 21 EUR/month, reduced rate 14.50 EUR/month (students and
    limited-income members). Both are parameters, not hardcoded.
  - One-time application fee of 25 EUR, waived for existing Toastmasters
    (self-declared by the guest; the email states the exemption).
  - Entry month shift: a guest reaching us after the 10th of a month is quoted
    from the *following* month, because only ~3 meetings happen per month and
    paying for a month you barely attend is a bad first impression.

The output is asserted byte-for-byte against the deployed n8n workflow in
``tests/test_fee.py`` via ``tests/fixtures/reference_cases.json``.
"""

from __future__ import annotations

import math

from clubops.domain.models import (
    DEFAULT_FEE_CONFIG,
    CivilDate,
    FeeConfig,
    Quote,
)

MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def assert_month(month: int) -> None:
    if not isinstance(month, int) or isinstance(month, bool) or month < 1 or month > 12:
        raise ValueError(f"Invalid month: {month}")


def round2(n: float) -> float:
    """Round to 2dp the way JavaScript's ``Math.round(n * 100) / 100`` does.

    Deliberately not Python's ``round()``: that is banker's rounding, so
    ``round(0.5)`` is ``0`` where JS gives ``1``. Every euro amount here would
    otherwise be a coin-flip away from the number the club published.
    """
    return math.floor(n * 100 + 0.5) / 100


def months_remaining_in_term(month: int) -> int:
    """Months left in the current term, counting the given month itself.

    April -> 6 ... September -> 1; October -> 6 ... March -> 1.
    """
    assert_month(month)
    if 4 <= month <= 9:
        return 10 - month  # Apr..Sep term
    idx = month + 12 if month <= 3 else month  # Oct=10 .. Mar=15
    return 16 - idx  # Oct..Mar term


def billable_months(month: int) -> int:
    """Billable months for an entry in the given month, applying the
    "last month of term rolls into the next term" rule."""
    remaining = months_remaining_in_term(month)
    return remaining + 6 if remaining == 1 else remaining


def resolve_start_month(date: CivilDate, cutoff_day: int) -> tuple[int, int]:
    """The (year, month) a guest's membership is quoted from, after the
    cutoff-day shift."""
    assert_month(date.month)
    if date.day <= cutoff_day:
        return date.year, date.month
    if date.month == 12:
        return date.year + 1, 1
    return date.year, date.month + 1


def format_period(start_year: int, start_month: int, months: int) -> str:
    """Human-readable coverage period, e.g. "August - September 2026",
    "October 2026 - March 2027", or "September 2026" for a single month.

    Uses an ASCII hyphen, matching the deployed workflow. ``n8n/lib/fee.js``
    uses an en dash; the deployed version is the one guests have received.
    """
    start_label = MONTH_NAMES[start_month - 1]
    end_offset = start_month - 1 + (months - 1)
    end_year = start_year + end_offset // 12
    end_month = (end_offset % 12) + 1
    if months == 1:
        return f"{start_label} {start_year}"
    if end_year == start_year:
        return f"{start_label} - {MONTH_NAMES[end_month - 1]} {start_year}"
    return f"{start_label} {start_year} - {MONTH_NAMES[end_month - 1]} {end_year}"


def format_euro(amount: float) -> str:
    """Format a euro amount the way the club writes it: 21, or 14.50."""
    return str(int(amount)) if float(amount).is_integer() else f"{amount:.2f}"


def calculate_fee(
    registered_on: CivilDate, config: FeeConfig = DEFAULT_FEE_CONFIG
) -> Quote:
    """Calculate the membership fee quote for one guest."""
    assert_month(registered_on.month)
    if not 1 <= registered_on.day <= 31:
        raise ValueError(f"invalid day {registered_on.day}")

    start_year, start_month = resolve_start_month(
        registered_on, config.current_month_cutoff_day
    )
    months = billable_months(start_month)

    membership_fee_standard = round2(months * config.standard_monthly_fee)
    membership_fee_reduced = round2(months * config.reduced_monthly_fee)
    total_standard = round2(membership_fee_standard + config.application_fee)

    return Quote(
        start_year=start_year,
        start_month=start_month,
        start_month_name=MONTH_NAMES[start_month - 1],
        months=months,
        period=format_period(start_year, start_month, months),
        shifted=not registered_on.day <= config.current_month_cutoff_day,
        standard_monthly_fee=config.standard_monthly_fee,
        reduced_monthly_fee=config.reduced_monthly_fee,
        application_fee=config.application_fee,
        membership_fee_standard=membership_fee_standard,
        membership_fee_reduced=membership_fee_reduced,
        total_standard=total_standard,
        total_reduced=round2(membership_fee_reduced + config.application_fee),
        # The literal arithmetic line used in the email, e.g. "2 x 21 + 25 = 67 Euros"
        calculation_line=(
            f"{months} x {format_euro(config.standard_monthly_fee)}"
            f" + {format_euro(config.application_fee)}"
            f" = {format_euro(total_standard)} Euros"
        ),
    )
