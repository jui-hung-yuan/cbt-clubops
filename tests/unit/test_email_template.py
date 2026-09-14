"""The rendered email must be character-identical to the deployed n8n output.

The wording is the club's, not ours. A diff here means a guest would receive a
different letter than the one n8n has been drafting, so the comparison is exact
rather than fuzzy.
"""

import json
from pathlib import Path

import pytest

from clubops.domain.email_template import render_membership_email
from clubops.domain.fee import calculate_fee
from clubops.domain.models import DEFAULT_CLUB_DETAILS, ClubDetails
from clubops.domain.timestamps import parse_timestamp

FIXTURE = Path(__file__).parent.parent / "fixtures" / "reference_cases.json"
REFERENCE_CASES = json.loads(FIXTURE.read_text())["cases"]


def _render(case):
    quote = calculate_fee(parse_timestamp(case["row"]["Timestamp"]))
    guest_name = str(case["row"].get("First and last name") or "").strip()
    return render_membership_email(guest_name, quote)


@pytest.mark.parametrize("case", REFERENCE_CASES, ids=lambda c: c["label"])
def test_body_matches_deployed_n8n_output(case):
    assert _render(case).body_html == case["emailBody"]


@pytest.mark.parametrize("case", REFERENCE_CASES, ids=lambda c: c["label"])
def test_subject_matches_deployed_n8n_output(case):
    assert _render(case).subject == case["emailSubject"]


def test_a_guest_name_cannot_break_the_markup():
    case = next(c for c in REFERENCE_CASES if c["label"] == "html-hostile-name")
    body = _render(case).body_html
    assert "Anne &lt;Annie&gt; &quot;A&amp;B&quot; Meyer" in body
    assert "<Annie>" not in body


# --- Club details are configuration ---------------------------------------
# The bank account and the signature belong to named people, so they are not in
# the source. These tests pin the two halves of that: the letter renders them
# from configuration, and the default is an obvious placeholder rather than
# anyone's real account.


def test_the_bank_block_and_signature_come_from_configuration():
    case = REFERENCE_CASES[0]
    quote = calculate_fee(parse_timestamp(case["row"]["Timestamp"]))
    club = ClubDetails(
        bank_iban="DE99 8888 7777 6666 5555 44",
        bank_bic="TESTDEFFXXX",
        bank_name="TEST BANK",
        bank_owner="Someone Else",
        signature_name="A. N. Other, VP Membership",
    )

    body = render_membership_email("Ada", quote, club).body_html

    for value in (
        club.bank_iban,
        club.bank_bic,
        club.bank_name,
        club.bank_owner,
        club.signature_name,
    ):
        assert value in body
    assert DEFAULT_CLUB_DETAILS.bank_iban not in body


def test_the_default_iban_is_obviously_not_a_real_account():
    """The safe failure for a missing configuration is a guest who asks what
    this is, not a guest who pays the wrong person."""
    assert DEFAULT_CLUB_DETAILS.bank_iban == "DE00 0000 0000 0000 0000 00"
    assert DEFAULT_CLUB_DETAILS.bank_owner == "Club Treasurer"


def test_no_real_club_details_are_committed_in_the_fixture():
    """The fixture is n8n's own output and once carried the real account. It is
    normalised onto the placeholders; regenerating it must re-apply that."""
    blob = FIXTURE.read_text()
    assert DEFAULT_CLUB_DETAILS.bank_iban in blob
    assert DEFAULT_CLUB_DETAILS.signature_name in blob
