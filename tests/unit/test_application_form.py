"""The pure half of the PandaDoc document: field declarations and names.

Field roles, types and required-ness live in the tags drawn into the PDF, and
are asserted in test_form_fields_pdf.py against the artefact itself. What is
left here is what this module actually decides.
"""

from __future__ import annotations

import pytest

from clubops.domain.application_fields import FIELDS
from clubops.domain.application_form import (
    APPLICANT_ROLE,
    OFFICER_ROLE,
    ROLES,
    build_field_assignments,
    document_name,
    split_name,
)


def test_every_tag_is_declared():
    """PandaDoc drops any tag whose id is missing from the fields object.

    It does not report this: the document is created successfully with the
    field simply absent. An upload that produced a blank form was exactly this.
    """
    assignments = build_field_assignments()
    assert set(assignments) == {name for name, _, _, _ in FIELDS}


def test_nothing_is_prefilled():
    """The Total needs the tier and whether the joining fee is waived, neither
    of which a name and an email carry. So the form goes out blank."""
    for name, entry in build_field_assignments().items():
        assert entry["value"] in ("", False), name


def test_checkboxes_are_declared_with_a_boolean():
    kinds = {name: kind for name, _, kind, _ in FIELDS}
    for name, entry in build_field_assignments().items():
        expected = False if kinds[name] == "checkbox" else ""
        assert entry["value"] == expected, name


def test_every_declaration_names_a_known_role():
    for name, entry in build_field_assignments().items():
        assert entry["role"] in ROLES, name


def test_both_signers_own_fields():
    roles = {entry["role"] for entry in build_field_assignments().values()}
    assert roles == {APPLICANT_ROLE, OFFICER_ROLE}


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        ("Ada Lovelace", ("Ada", "Lovelace")),
        ("Maria von der Leyen", ("Maria von der", "Leyen")),
        ("Prince", ("Prince", "")),
        ("  Ada   Lovelace  ", ("Ada", "Lovelace")),
    ],
)
def test_names_split_on_the_last_token(full_name, expected):
    assert split_name(full_name) == expected


def test_an_empty_name_is_refused():
    with pytest.raises(ValueError):
        split_name("   ")


def test_the_document_is_named_after_the_guest():
    """How a human finds the right draft in a list of them.

    No separator between title and name. A sandbox key still prefixes "[DEV]",
    which is PandaDoc's and disappears with a production key.
    """
    assert document_name("Ada Lovelace") == "CBT Membership Application Ada Lovelace"
    assert document_name("  Ada   Lovelace ") == (
        "CBT Membership Application Ada Lovelace"
    )
