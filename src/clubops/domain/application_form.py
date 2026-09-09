"""Turning a guest into a PandaDoc application document's parameters.

Nothing here fills a value in. The document goes out blank on purpose: the
Total depends on two facts a name and an email address do not carry — whether
the standard or reduced tier applies, and whether the 25 EUR application fee is
waived because the applicant is already a Toastmaster. Guessing either would
put a wrong number in front of a guest, so the fields are placed and assigned,
and the people they belong to fill them in.

That is also why this module does not import ``fee``.

There is deliberately no field-assignment code here. Field roles travel in the
tags drawn into the PDF by scripts/build_form_fields.py, so the API request
needs only the recipients — the two role names below are the contract between
those tags and the recipients array, and nothing else.
"""

from __future__ import annotations

from clubops.domain.application_fields import FIELDS

APPLICANT_ROLE = "applicant"
OFFICER_ROLE = "officer"

ROLES = (APPLICANT_ROLE, OFFICER_ROLE)

# Must match the type name the build script writes into the tags. It was left
# at the shorthand "c" when the tags moved to long names, which quietly declared
# every checkbox with a string value instead of a boolean.
CHECKBOX = "checkbox"


def build_field_assignments() -> dict[str, dict[str, object]]:
    """Declare every tag's optId, with no value filled in.

    This is not optional and not redundant with the tags. PandaDoc requires it:
    *"All field tags within PDF must be declared within fields object."* Leave a
    tag out and it is not turned into a field — and the document is still
    created, successfully, just without it. An upload that came back with a
    clean but completely empty form was this, with no error to point at it.

    ``value`` is a required property on each entry, so a field we are not
    prefilling is declared with an empty one. Checkboxes take a boolean.
    """
    return {
        name: {"value": False if kind == CHECKBOX else "", "role": role}
        for name, role, kind, _ in FIELDS
    }


def split_name(full_name: str) -> tuple[str, str]:
    """Split "First and last name" into the two parts PandaDoc wants.

    The registration sheet holds one name string; PandaDoc recipients take
    ``first_name`` and ``last_name`` separately. The last whitespace-separated
    token is treated as the surname and everything before it as the given name,
    which is right for "Ada Lovelace" and for "Maria von der Leyen", and wrong
    for surnames written first. A single token becomes the first name, leaving
    the surname empty rather than inventing one.
    """
    parts = full_name.split()
    if not parts:
        raise ValueError("cannot build a document without a name")
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def document_name(full_name: str) -> str:
    """The document's title in PandaDoc's list, which is how a human finds it.

    A sandbox API key prefixes this with "[DEV]" and PandaDoc gives you no
    control over that — it is one of the two things a production key removes,
    the other being the watermark on the PDF.
    """
    return f"CBT Membership Application {' '.join(full_name.split())}"
