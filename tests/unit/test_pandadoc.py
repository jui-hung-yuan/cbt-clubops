"""The PandaDoc request payload, and the guarantee that nothing sends."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from clubops.domain.application_form import APPLICANT_ROLE, OFFICER_ROLE
from clubops.integrations import pandadoc
from clubops.integrations.pandadoc import build_document_payload, document_link

OFFICER_EMAIL = "cb.toastmasters.d95@gmail.com"
OFFICER_NAME = "Center Berlin Toastmasters"


def payload(name: str = "Ada Lovelace", email: str = "ada@example.com") -> dict:
    return build_document_payload(name, email, OFFICER_EMAIL, OFFICER_NAME)


def test_the_module_has_no_send_code_path():
    """The document is created for review, never sent for signature.

    PandaDoc's API key carries full send permission — nothing about the key or
    the plan prevents this, so the guarantee is that no send call exists in the
    module, exactly as with the Gmail adapter.

    Checked over the parsed tree rather than the raw text, so that prose
    explaining what the module refuses to do cannot fail the test, and a string
    literal quietly building a "/send" URL cannot pass it.
    """
    tree = ast.parse(Path(pandadoc.__file__).read_text())

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            found = ast.get_docstring(node, clean=False)
            if found:
                docstrings.add(found)

    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    ]
    assert not [text for text in literals if "send" in text.lower()]

    called = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    called |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not [name for name in called if "send" in name.lower()]


def test_both_signers_are_recipients():
    """The form is not valid without the applicant and a club officer."""
    recipients = payload()["recipients"]
    assert [r["role"] for r in recipients] == [APPLICANT_ROLE, OFFICER_ROLE]
    assert recipients[0]["email"] == "ada@example.com"
    assert recipients[1]["email"] == OFFICER_EMAIL


def test_the_guest_signs_first():
    """The officer countersigns an application that already exists."""
    recipients = payload()["recipients"]
    assert recipients[0]["signing_order"] < recipients[1]["signing_order"]


def test_the_guests_name_is_split_for_the_recipient():
    applicant = payload("Maria von der Leyen")["recipients"][0]
    assert applicant["first_name"] == "Maria von der"
    assert applicant["last_name"] == "Leyen"


def test_field_tag_parsing_is_requested():
    """False means "read field tags", which is what the PDF carries.

    True would read PDF form fields instead, and that path silently drops
    required-ness and date fields. The two are mutually exclusive.
    """
    assert payload()["parse_form_fields"] is False


def test_every_tag_is_declared_in_the_fields_object():
    """Not redundant with the tags, despite the tags carrying role and type.

    PandaDoc requires it — "All field tags within PDF must be declared within
    fields object" — and drops any tag that is missing, silently, while still
    creating the document.
    """
    from clubops.domain.application_fields import FIELDS as TAGGED

    assert set(payload()["fields"]) == {name for name, _, _, _ in TAGGED}


def test_the_recipient_roles_match_the_roles_the_tags_name():
    """A tag naming a role with no recipient produces an unassignable field."""
    from clubops.domain.application_fields import FIELDS as TAGGED

    declared = {r["role"] for r in payload()["recipients"]}
    assert {role for _, role, _, _ in TAGGED} <= declared


def test_a_missing_email_is_refused_before_upload():
    with pytest.raises(ValueError):
        build_document_payload("Ada Lovelace", "   ", OFFICER_EMAIL, OFFICER_NAME)


def test_the_annotated_form_ships_with_the_package():
    """The upload has nothing to send if the build script was never run."""
    assert pandadoc.FORM_PDF.exists()


def test_the_link_points_at_the_document():
    assert document_link("abc123").endswith("abc123")


# --- rate limits ----------------------------------------------------------

SANDBOX_REQUESTS_PER_MINUTE = 10


def test_polling_stays_within_the_sandbox_rate_limit():
    """A sandbox key allows 10 requests a minute; calibration happens on one.

    A tight poll loop burns the whole budget and fails with a 429 that reads
    like a broken upload. This pins the budget: the upload plus a full run of
    polls has to fit inside one minute's allowance.
    """
    creator = pandadoc.PandaDocApplicationCreator("key", OFFICER_EMAIL, OFFICER_NAME)

    elapsed = 0.0
    wait = creator._poll_interval
    requests_in_first_minute = 1  # the upload itself
    for _ in range(creator._poll_attempts):
        requests_in_first_minute += 1
        elapsed += wait
        wait = min(wait * 1.6, 12.0)
        if elapsed >= 60.0:
            break

    assert requests_in_first_minute <= SANDBOX_REQUESTS_PER_MINUTE


def test_polling_waits_long_enough_to_be_useful():
    """Backing off must not mean giving up while PandaDoc is still working."""
    creator = pandadoc.PandaDocApplicationCreator("key", OFFICER_EMAIL, OFFICER_NAME)

    total = 0.0
    wait = creator._poll_interval
    for _ in range(creator._poll_attempts - 1):
        total += wait
        wait = min(wait * 1.6, 12.0)

    assert total >= 30.0
