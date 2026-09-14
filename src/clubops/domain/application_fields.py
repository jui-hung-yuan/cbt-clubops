"""The application form's fields. Generated — do not edit.

Regenerate with::

    uv run python scripts/build_form_fields.py

Each row is (optId, role, type, required). The roles are carried by the
field tags drawn into the PDF, so the API does not need to assign them;
this exists so the tests can check the artefact without a PDF parser,
and so a human can see what the form asks for without opening it.
"""

from __future__ import annotations

FIELDS: tuple[tuple[str, str, str, bool], ...] = (
    ("lastname", "applicant", "textfield", True),
    ("firstname", "applicant", "textfield", True),
    ("address", "applicant", "textfield", True),
    ("city", "applicant", "textfield", True),
    ("postalcode", "applicant", "textfield", True),
    ("country", "applicant", "textfield", True),
    ("mobilephone", "applicant", "textfield", False),
    ("email", "applicant", "textfield", True),
    ("birthday", "applicant", "textfield", False),
    ("startdate", "applicant", "textfield", True),
    ("total", "officer", "textfield", False),
    ("prevclubname", "officer", "textfield", False),
    ("prevclubnumber", "officer", "textfield", False),
    ("membernumber", "officer", "textfield", False),
    ("mtn", "officer", "checkbox", False),
    ("mtd", "officer", "checkbox", False),
    ("mtr", "officer", "checkbox", False),
    ("mtw", "officer", "checkbox", False),
    ("mtt", "officer", "checkbox", False),
    ("gf", "applicant", "checkbox", False),
    ("gm", "applicant", "checkbox", False),
    ("go", "applicant", "checkbox", False),
    ("f1", "officer", "checkbox", False),
    ("f2", "officer", "checkbox", False),
    ("f3", "officer", "checkbox", False),
    ("f4", "officer", "checkbox", False),
    ("f5", "officer", "checkbox", False),
    ("f6", "officer", "checkbox", False),
    ("cm", "applicant", "checkbox", False),
    ("ce", "applicant", "checkbox", False),
    ("cp", "applicant", "checkbox", False),
    ("slast", "officer", "textfield", False),
    ("sfirst", "officer", "textfield", False),
    ("smem", "officer", "textfield", False),
    ("sclub", "officer", "textfield", False),
    ("sd", "applicant", "date", True),
    ("asig", "applicant", "signature", True),
    ("osig", "officer", "signature", True),
    ("cy", "applicant", "checkbox", False),
    ("cn", "applicant", "checkbox", False),
    ("consentemail", "applicant", "textfield", False),
    ("printedname", "applicant", "textfield", True),
    ("psig", "applicant", "signature", True),
    ("pd", "applicant", "date", True),
)

FIELD_NAMES: tuple[str, ...] = tuple(name for name, _, _, _ in FIELDS)
