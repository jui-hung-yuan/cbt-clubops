"""Timestamp parsing, ported from the n8n Code node.

The sheet is German-locale, so 05/08/2026 is 5 August. Getting the order wrong
silently shifts a guest's quote by months, which is why this is parsed
explicitly rather than by a general-purpose date parser.
"""

import pytest

from clubops.domain.models import CivilDate
from clubops.domain.timestamps import (
    is_before_cutoff,
    parse_timestamp,
    to_comparable,
)


def test_iso_timestamps_parse_directly():
    assert parse_timestamp("2026-08-05") == CivilDate(2026, 8, 5)
    assert parse_timestamp("2026-08-05 14:35:20") == CivilDate(2026, 8, 5)
    assert parse_timestamp("2026-08-05T14:35:20Z") == CivilDate(2026, 8, 5)


def test_slash_and_dot_separators_are_both_accepted():
    assert parse_timestamp("05/08/2026 14:35:20") == CivilDate(2026, 8, 5)
    assert parse_timestamp("05.08.2026 14:35:20") == CivilDate(2026, 8, 5)


def test_ambiguous_dates_follow_the_configured_order():
    assert parse_timestamp("05/08/2026", date_order="DMY") == CivilDate(2026, 8, 5)
    assert parse_timestamp("05/08/2026", date_order="MDY") == CivilDate(2026, 5, 8)


def test_a_component_over_12_resolves_the_order_regardless_of_configuration():
    # 25 cannot be a month, so this is unambiguous under either setting.
    assert parse_timestamp("25/08/2026", date_order="MDY") == CivilDate(2026, 8, 25)
    assert parse_timestamp("08/25/2026", date_order="DMY") == CivilDate(2026, 8, 25)


def test_surrounding_whitespace_is_tolerated():
    assert parse_timestamp("  2026-08-05  ") == CivilDate(2026, 8, 5)


def test_bad_input_fails_loudly_rather_than_guessing():
    with pytest.raises(ValueError, match="empty Timestamp"):
        parse_timestamp("")
    with pytest.raises(ValueError, match="empty Timestamp"):
        parse_timestamp(None)
    with pytest.raises(ValueError, match="empty Timestamp"):
        parse_timestamp("   ")
    with pytest.raises(ValueError, match="Unrecognised Timestamp format"):
        parse_timestamp("last Tuesday")


def test_comparable_ordering_is_chronological():
    assert to_comparable(CivilDate(2026, 8, 5)) < to_comparable(CivilDate(2026, 8, 12))
    assert to_comparable(CivilDate(2026, 8, 31)) < to_comparable(CivilDate(2026, 9, 1))
    assert to_comparable(CivilDate(2026, 12, 31)) < to_comparable(CivilDate(2027, 1, 1))


def test_the_cutoff_is_inclusive_of_the_go_live_day():
    cutoff = CivilDate(2026, 8, 12)
    assert is_before_cutoff(CivilDate(2026, 8, 11), cutoff) is True
    assert is_before_cutoff(CivilDate(2026, 8, 12), cutoff) is False
    assert is_before_cutoff(CivilDate(2026, 8, 13), cutoff) is False
