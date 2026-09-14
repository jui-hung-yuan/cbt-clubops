"""The committed PDF is a build artefact, so it is checked like one.

Every assertion here is a bug that reached a real upload. Field geometry is
invisible in a diff and PandaDoc reports none of these — it creates the document
successfully and simply places nothing, or places it wrong. So the checks live
here instead:

  - tags must be extractable            (drawn in text render mode 3: 0 fields)
  - tags must use curly braces          (square brackets: 0 fields)
  - ids must be unique                  (two "signature" tags: one silently lost)
  - the manifest must match the PDF     (an undeclared tag is dropped, silently)
  - fields must not collide             (sponsor row rendered as one long bar)
  - tags must not run off the page      (a field that may not place at all)
  - tags must not erase the form        (white glyphs cut "14.50 EUR per month")
  - checkboxes must clear their labels  (boxes swallowed "New", "Dual", "female")
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from pypdf import PdfReader

from clubops.domain.application_fields import FIELDS as MANIFEST
from clubops.domain.application_form import ROLES
from clubops.integrations.pandadoc import FORM_PDF

_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "build_form_fields.py"
_spec = importlib.util.spec_from_file_location("build_form_fields", _SCRIPT)
build_form_fields = importlib.util.module_from_spec(_spec)
# Registered before executing: the module defines a dataclass, and dataclasses
# resolves annotations through sys.modules.
sys.modules["build_form_fields"] = build_form_fields
_spec.loader.exec_module(build_form_fields)

SPECS = build_form_fields.FIELDS

# Where each option's printed label begins, measured off the source form. A
# checkbox is as wide as its tag, and anything reaching these covers the word.
LABEL_X = {
    "mtn": 328.6,
    "mtd": 328.6,
    "mtr": 328.6,
    "mtw": 328.6,
    "mtt": 328.6,
    "f1": 328.6,
    "f2": 328.6,
    "f3": 328.6,
    "f4": 328.6,
    "f5": 328.6,
    "f6": 328.6,
    "gf": 124.1,
    "gm": 190.6,
    "go": 250.5,
    "cm": 46.6,
    "ce": 118.6,
    "cp": 181.8,
}
MIN_LABEL_GAP = 1.0


@pytest.fixture(scope="module")
def page_text() -> list[str]:
    reader = PdfReader(str(FORM_PDF))
    return [page.extract_text() or "" for page in reader.pages]


def test_every_tag_is_in_the_text_layer(page_text):
    """PandaDoc finds tags by reading the text; anything it cannot read is lost.

    An earlier build drew them in text rendering mode 3, which paints nothing.
    pypdf still extracted them, so the file looked right locally while PandaDoc
    placed zero fields and reported success.
    """
    found = sum(text.count("{") for text in page_text)
    assert found == len(SPECS)


def test_tags_use_curly_braces(page_text):
    """PandaDoc's own sample uses {type:role:id}. Square brackets place nothing."""
    for spec in SPECS:
        tag = spec.tag()
        assert tag.startswith("{") and tag.endswith("}"), tag
        assert "[" not in tag and "]" not in tag, tag


def test_the_asterisk_is_attached_to_the_type():
    """ "{checkbox*:role:id}", not "[checkbox:*:role:id]" — the latter is inert.

    Omitting it is what marks a field required, so this is also what carries
    required-ness at all.
    """
    for spec in SPECS:
        if spec.required:
            assert "*" not in spec.tag(), spec.tag()
        else:
            assert re.match(r"^\{[a-z]+\*:", spec.tag()), spec.tag()


def test_tag_ids_are_unique():
    """Two tags sharing an id collapse into one entry and one is dropped."""
    names = [spec.name for spec in SPECS]
    assert len(names) == len(set(names))


def test_tag_ids_carry_no_underscores():
    """Trailing underscores are how a tag sets its width."""
    for spec in SPECS:
        assert "_" not in spec.name, spec.name


def test_the_manifest_matches_the_pdf():
    """The runtime declares fields from the manifest without opening the PDF.

    A tag missing from the fields object is not placed, and nothing says so.
    """
    assert sorted(name for name, _, _, _ in MANIFEST) == sorted(
        spec.name for spec in SPECS
    )


def test_every_field_names_a_known_role():
    for _, role, _, _ in MANIFEST:
        assert role in ROLES


def test_both_roles_own_fields():
    assert {role for _, role, _, _ in MANIFEST} == set(ROLES)


def test_no_two_fields_collide():
    """A field is as wide as its tag, which is easy to forget on a narrow slot."""
    assert build_form_fields.collisions(SPECS) == []


def test_no_tag_runs_off_the_page():
    widths = [float(page.mediabox.width) for page in PdfReader(str(FORM_PDF)).pages]
    over = [s for s in SPECS if build_form_fields.overflows(s, widths[s.page])]
    assert over == []


@pytest.mark.parametrize("name", sorted(LABEL_X))
def test_checkboxes_clear_their_labels(name):
    spec = next(s for s in SPECS if s.name == name)
    right = spec.x + build_form_fields.tag_width(spec)
    assert right <= LABEL_X[name] - MIN_LABEL_GAP


def test_the_tags_erase_nothing_but_the_circles_they_replace():
    """Tags are drawn in white, and white paints.

    Three of them once sat over printed content and cut it out — most visibly
    "14.50 EUR per month..." in the right-hand column. Only the circles each
    checkbox replaces are meant to disappear.
    """
    scale = 3.0
    original = pdfium.PdfDocument(str(build_form_fields.SOURCE))
    pages = [original[i].render(scale=scale).to_pil().convert("L") for i in range(3)]
    intended = [(s.page, *s.erase) for s in SPECS if s.erase]

    damage = 0
    for spec in SPECS:
        image = pages[spec.page]
        pixels = image.load()
        width, height = image.size
        size = spec.size()
        x0, x1 = spec.x, spec.x + build_form_fields.tag_width(spec)
        top, bottom = spec.baseline - 0.72 * size, spec.baseline + 0.21 * size
        for x in range(max(0, int(x0 * scale)), min(width, int(x1 * scale) + 1)):
            for y in range(
                max(0, int(top * scale)), min(height, int(bottom * scale) + 1)
            ):
                if pixels[x, y] >= 128:
                    continue
                if any(
                    page == spec.page
                    and ex0 - 2 <= x / scale <= ex1 + 2
                    and etop - 2 <= y / scale <= ebottom + 2
                    for page, ex0, etop, ex1, ebottom in intended
                ):
                    continue
                damage += 1
    assert damage == 0


def test_both_signatures_are_the_same_size():
    """The officer's box was half again the applicant's, for no reason at all.

    A field is as wide as its tag and its height follows its width, so an
    over-padded tag simply made a bigger box.
    """
    widths = [
        build_form_fields.tag_width(s)
        for s in SPECS
        if s.kind == build_form_fields.SIGNATURE
    ]
    assert max(widths) - min(widths) < 10.0


def test_the_two_dates_are_date_fields():
    dates = {s.name for s in SPECS if s.kind == build_form_fields.DATE}
    assert dates == {"sd", "pd"}


# --- The bank block -------------------------------------------------------
# The club's IBAN, BIC, bank and account owner belong to a named person, so the
# committed source has that column emptied and the values are drawn at build
# time. These tests pin both halves: the artefact is complete, and it is
# complete with placeholders rather than anyone's account.

BANK_PLACEHOLDERS = ("DE00 0000 0000 0000 0000 00", "XXXXDEXXXXX", "EXAMPLE BANK",
                     "Club Treasurer")


def _all_text(path):
    return "".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


@pytest.mark.parametrize("value", BANK_PLACEHOLDERS)
def test_the_committed_form_carries_placeholder_bank_details(value):
    """A clone with no configuration must still build a complete form — and one
    nobody could mistake for a real account."""
    assert value in _all_text(build_form_fields.OUTPUT)


def test_the_source_form_carries_no_bank_values_at_all():
    """scripts/redact_source_form.py removed them, and covering text with a white
    box would not have: the glyphs would still be in the content stream."""
    text = "".join(_all_text(build_form_fields.SOURCE).split())
    for label in ("IBAN:", "BIC:", "Bank:", "Owner:"):
        assert label.replace(" ", "") in text, "the labels must remain"
    for value in ("DE00", "XXXXDEXXXXX", "EXAMPLEBANK", "ClubTreasurer"):
        assert value not in text, "the source must not carry values of its own"


# Any German IBAN and any BIC, not this club's in particular. A guard written
# against the real values would have to contain them, which is the thing being
# guarded against — and this way it also catches the next treasurer's account.
IBAN_SHAPED = re.compile(r"DE\d{2}[\d ]{18,24}")
BIC_SHAPED = re.compile(r"\b[A-Z]{4}DE[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")


@pytest.mark.parametrize("path_name", ["SOURCE", "OUTPUT"])
def test_no_real_bank_details_are_committed(path_name):
    """The regression guard for the whole exercise. This repository is public.

    The placeholders are the only bank-shaped strings allowed in either PDF, so
    a source regenerated from the club's original without redacting it fails
    here rather than reaching GitHub.
    """
    text = _all_text(getattr(build_form_fields, path_name))

    for match in IBAN_SHAPED.findall(text):
        assert match.strip().startswith("DE00 0000"), f"a real IBAN is committed: {match[:9]}…"
    for match in BIC_SHAPED.findall(text):
        assert match == "XXXXDEXXXXX", f"a real BIC is committed: {match[:4]}…"


def test_the_bank_values_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("BANK_IBAN", "DE99 1234 5678 9012 3456 78")
    monkeypatch.setenv("BANK_OWNER", "Someone Real")

    values = {env: value for env, _, value in build_form_fields.bank_values()}

    assert values["BANK_IBAN"] == "DE99 1234 5678 9012 3456 78"
    assert values["BANK_OWNER"] == "Someone Real"
    # Unset stays on the placeholder rather than drawing an empty line.
    assert values["BANK_BIC"] == "XXXXDEXXXXX"


def test_an_empty_environment_variable_keeps_the_placeholder(monkeypatch):
    """A build arg that was declared but never given a value must not produce a
    form with a blank IBAN, which reads as an oversight rather than a mistake."""
    monkeypatch.setenv("BANK_IBAN", "   ")
    values = {env: value for env, _, value in build_form_fields.bank_values()}
    assert values["BANK_IBAN"] == "DE00 0000 0000 0000 0000 00"
