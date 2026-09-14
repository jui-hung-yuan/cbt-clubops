"""Write PandaDoc field tags into the CBT membership application form.

    uv run python scripts/build_form_fields.py

The source PDF in ``docs/`` is completely flat: ``get_fields()`` returns None and
all three pages carry zero annotations. PandaDoc has no coordinate-placement
API, so field positions can only come from inside the file it is given. This
script puts them there, once, so every upload lands them identically.

**Why tags and not PDF form fields.** The first version of this script wrote
real AcroForm fields and uploaded with ``parse_form_fields: true``. Placement
worked, but PandaDoc discards two things on that path, and its own docs say so:

- *"Auto-placed fields are 'not required' by default"* — the AcroForm required
  flag is dropped, and the Update Document API cannot set it afterwards
  (that endpoint changes field *values* only, not field properties).
- An Acrobat date-formatted text field imports as plain text, so the signer
  types a date instead of picking one.

Field tags are the one documented mechanism that carries field type, recipient
role and required-ness together. They are mutually exclusive with form fields —
``parse_form_fields`` must be false, and PandaDoc warns that a file containing
both produces duplicate, overlapping fields.

A tag is literal text in the PDF, which PandaDoc finds and swaps for a field:

    {fieldType*:role:optId_____}

Curly braces, and the ``*`` attached to the type — verbatim from PandaDoc's own
sample tag PDF, which places every tag it contains. The square-bracket form with
the asterisk as a separate position, ``[fieldType:*:role:optId]``, appears in a
summary of the developer docs and places nothing at all, silently. Six uploads
went on establishing that; the sample is the authority.

``*`` marks a field **not** required, so omitting it is the required case.
Trailing underscores widen the field: PandaDoc scales it "to match the length
and size of the tag", so tag width and font size are what set field width and
font size.

Tags are drawn in white, per PandaDoc's instruction to match the tag colour to
the background — and NOT in text rendering mode 3, which leaves glyphs
extractable locally while PandaDoc sees nothing.

It writes two artefacts, both checked in:

  src/clubops/assets/cbt_application_form_fields.pdf
  src/clubops/domain/application_fields.py   (the field manifest)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "src" / "clubops" / "assets"
# Both live here: the club's form with its bank column emptied, and the tagged
# artefact built from it. Keeping the input beside the output means the Docker
# build needs nothing from docs/, so the build context has no negated ignore
# patterns to get quietly wrong.
SOURCE = ASSETS / "CBT_application_form_2026_fees_v2.pdf"
OUTPUT = ASSETS / "cbt_application_form_fields.pdf"
MANIFEST = REPO / "src" / "clubops" / "domain" / "application_fields.py"

# The tag's own font size becomes the field's font size, so this is now a direct
# lever rather than the box-height guessing the AcroForm version needed.
FONT_SIZE = 11

# --- The bank block ------------------------------------------------------
# The source form's value column is empty: it held a named person's IBAN, BIC,
# bank and name, and this repository is public, so scripts/redact_source_form.py
# removed them. They are drawn back in here.
#
# Defaults are obvious placeholders, so a clone with no configuration builds a
# complete, correct form that no one could mistake for a real account. The real
# values arrive as environment variables at image build time — see the Dockerfile
# — which is also when the email template gets them, so the letter and the form
# can never disagree.
#
# Coordinates are the source's own: PDF user space, origin bottom-left, taken
# from where the removed text sat.
BANK_VALUE_X = 374.0
BANK_VALUE_SIZE = 10.5
BANK_ROWS = (
    ("BANK_IBAN", 142.7, "DE00 0000 0000 0000 0000 00"),
    ("BANK_BIC", 128.2, "XXXXDEXXXXX"),
    ("BANK_NAME", 113.7, "EXAMPLE BANK"),
    ("BANK_OWNER", 99.3, "Club Treasurer"),
)
BANK_PAGE = 0

# A checkbox's width follows its TAG's width. Measured on a real document: a
# 25pt-wide tag produced a box that ran from x=306 to x=331 and swallowed the
# first letter of "New", "Dual", "Reinstated" and the rest.
#
# The form gives very little room. The officer column's circle sits at
# x=315.3-323.1 with its label at 328.6; the gender row is tighter still, with
# "Gender* :" ending at 110.7, the circle at 113.5-121.5 and "female" at 124.1.
# Roughly 13pt of clear space, so the box is sized to 11 and the tag's font is
# computed per checkbox to make the tag exactly that wide — see
# FieldSpec.size(). The ids are kept short for the same reason: every character
# in the tag has to fit inside 11 points.
CHECKBOX_BOX_WIDTH = 11.0

# PandaDoc anchors a field at the tag's baseline and grows it upwards. So the
# baseline has to sit BELOW the printed circle for the box to land on it — the
# first attempt lifted the tag above the circle and put every checkbox in the
# row above, covering that line's text.
#
# These two numbers are the whole adjustment, measured off a rendered document:
# drop is how far below the circle's top edge the baseline goes, nudge shifts it
# left so the box straddles the circle instead of the label. Re-measure and
# change them here if PandaDoc's checkbox size ever differs.
CHECKBOX_BASELINE_DROP = 10.0

# How far left of the circle the box starts. Per row, because the room varies:
# the officer column has an empty gutter to its left and can afford 6pt, while
# the gender row is boxed in between "Gender* :" ending at 110.7 and "female"
# starting at 124.1.
CHECKBOX_X_NUDGE = -2.0

# The gutter between the form's two columns. The left column's printed lines
# stop at 274.8 and the right column starts at 315.3.
COLUMN_DIVIDE = 300.0

APPLICANT = "applicant"
OFFICER = "officer"

# Long names, verbatim from PandaDoc's own sample tag PDF. Shorthand (t/c/s/d)
# is documented too, but the sample is the only form proven to place, and this
# has already cost enough uploads.
TEXT = "textfield"
DATE = "date"
SIGNATURE = "signature"
CHECKBOX = "checkbox"

# Helvetica advance widths per 1000 units, for the characters a tag can contain.
# Needed to work out how many underscores reach a target field width; there is
# no font metrics library in the tree and this is the whole of what one would be
# used for.
_WIDTHS = {
    "{": 334,
    "}": 334,
    ":": 278,
    "*": 389,
    "_": 556,
    " ": 278,
    "a": 556,
    "b": 556,
    "c": 500,
    "d": 556,
    "e": 556,
    "f": 278,
    "g": 556,
    "h": 556,
    "i": 222,
    "j": 222,
    "k": 500,
    "l": 222,
    "m": 833,
    "n": 556,
    "o": 556,
    "p": 556,
    "q": 556,
    "r": 333,
    "s": 500,
    "t": 278,
    "u": 556,
    "v": 500,
    "w": 722,
    "x": 500,
    "y": 500,
    "z": 500,
}


def _text_width(text: str, size: float) -> float:
    return sum(_WIDTHS.get(char, 556) for char in text) * size / 1000.0


@dataclass(frozen=True)
class FieldSpec:
    """One field, declared where its tag's baseline sits on the page.

    Coordinates are top-down (pdfplumber/screen), because that is how the
    geometry was measured off the real file. The flip to PDF's bottom-left
    origin happens once, in :func:`_draw`.
    """

    name: str  # the optId. No underscores: trailing ones set field width.
    page: int
    kind: str
    x: float
    baseline: float
    width: float
    required: bool = True
    role: str | None = None  # None means "derive from x"
    font_size: float = 0  # 0 means "use the default for this kind"
    # Region of the printed form to paint over, in top-down coords. Used to
    # erase the circle a checkbox replaces, so the page does not show both.
    erase: tuple[float, float, float, float] | None = None

    def resolved_role(self) -> str:
        if self.role is not None:
            return self.role
        if self.page == 2:
            return APPLICANT
        return APPLICANT if self.x < COLUMN_DIVIDE else OFFICER

    def size(self) -> float:
        """Font size for the tag — which is what sets the field's size.

        Checkboxes get a computed one: the tag has to be exactly
        CHECKBOX_BOX_WIDTH wide, because PandaDoc scales the box to the tag, and
        anything wider covers the label beside it. That works out around a
        point, which is fine — font size does not affect text extraction, and
        the tag is invisible anyway.
        """
        if self.font_size:
            return self.font_size
        if self.kind != CHECKBOX:
            return FONT_SIZE
        return self.width / _text_width(self._bare_tag(), 1.0)

    def _bare_tag(self) -> str:
        optional = "*" if not self.required else ""
        return f"{{{self.kind}{optional}:{self.resolved_role()}:{self.name}}}"

    def tag(self) -> str:
        """The literal text PandaDoc swaps for a field.

        Curly braces, and the asterisk attached to the type. Verbatim from
        PandaDoc's own sample tag PDF, which places 6 of 6::

            {textfield:user________________}
            {checkbox*:user:like}
            {signature:user_______}

        Square brackets with the asterisk as its own colon-separated position —
        ``[checkbox:*:user:like]`` — is what a summary of the developer docs
        describes. It places nothing, silently. The sample is the authority.

        Omitting the asterisk is what makes a field required, so required is the
        default rather than something to be switched on.
        """
        optional = "*" if not self.required else ""
        head = f"{{{self.kind}{optional}:{self.resolved_role()}:{self.name}"
        size = self.size()
        pad = max(
            0,
            int((self.width - _text_width(head + "}", size)) / _text_width("_", size)),
        )
        return f"{head}{'_' * pad}}}"


def _on_line(
    name: str,
    page: int,
    x0: float,
    x1: float,
    bottom: float,
    required: bool = True,
    kind: str = TEXT,
    font_size: float = 0,
    lift: float = 0.0,
) -> FieldSpec:
    """A field sitting on a printed line, given that line's bottom edge.

    ``lift`` raises the tag off that line. Tags are drawn in white and white
    paints, so a tag sharing a baseline with the form's printed rule chews gaps
    out of it. Four points is enough to clear the rule while still reading as
    sitting on it.
    """
    return FieldSpec(
        name,
        page,
        kind,
        x0,
        bottom - lift,
        x1 - x0,
        required=required,
        font_size=font_size,
    )


def _check(
    name: str,
    page: int,
    x0: float,
    top: float,
    nudge: float = CHECKBOX_X_NUDGE,
    width: float = CHECKBOX_BOX_WIDTH,
) -> FieldSpec:
    """A checkbox replacing one of the form's printed circles.

    Positioned so the control lands on the printed circle rather than in the row
    above it — see CHECKBOX_BASELINE_DROP. The tag itself is far wider than the
    circle, but drawn at 3pt its white glyphs are too small to disturb the label.

    Never required: every checkbox here belongs to a group where the signer
    picks one, and PandaDoc has no notion of "one of these three".
    """
    return FieldSpec(
        name,
        page,
        CHECKBOX,
        x0 + nudge,
        top + CHECKBOX_BASELINE_DROP,
        width,
        required=False,
        erase=(x0 - 1.0, top - 1.0, x0 + 9.0, top + 11.0),
    )


# --- page 1 -----------------------------------------------------------------
#
# The applicant fields are inline: on the label's own row rather than on the
# underscore line below it, matching how Birthday and "Membership to begin on"
# already read. Every label ends at x~110.7, so they align on x0=115. The band
# runs to 300 rather than the printed 274.8 to buy back width for Address.
_INLINE_X0, _INLINE_X1 = 115.0, 300.0

# required mirrors the asterisks printed on the form itself. Mobile phone and
# birthday carry none, so they stay optional.
PAGE1_INLINE = [
    ("lastname", 304.3, True),
    ("firstname", 337.3, True),
    ("address", 441.7, True),
    ("city", 474.7, True),
    ("postalcode", 507.7, True),
    ("country", 540.7, True),
    ("mobilephone", 573.7, False),
    ("email", 606.8, True),
]

FIELDS: list[FieldSpec] = [
    _on_line(name, 0, _INLINE_X0, _INLINE_X1, baseline, required=required)
    for name, baseline, required in PAGE1_INLINE
]

FIELDS += [
    # Already inline on the printed form, so their x-extents are kept.
    _on_line("birthday", 0, 124.2, 190.8, 370.3, required=False, lift=4),
    # 8pt. At 11pt this tag is 138pt wide, running from x=210.8 well past the
    # column divide at 315.3 and painting white over "14.50 EUR per month..." in
    # the right-hand column. There is no room to start it further left — the
    # label ends at x=208 — so the tag has to be narrower.
    _on_line("startdate", 0, 210.8, 277.5, 639.8, lift=4, font_size=8),
    # 8pt. Only 83pt of page remains to the right of the Total rule, and the
    # tag is 87pt at 9pt and 112pt at 11pt. Starting it further left would put
    # white glyphs over the printed euro sign. It is an officer-filled number,
    # so the odd size out costs least here.
    _on_line("total", 0, 511.9, 556.4, 586.3, required=False, font_size=8, lift=4),
    # Transfer block, right column — only filled in when someone transfers.
    _on_line("prevclubname", 0, 429.1, 556.9, 284.1, required=False, lift=4),
    _on_line("prevclubnumber", 0, 428.7, 556.6, 307.3, required=False, lift=4),
    _on_line("membernumber", 0, 428.9, 556.3, 328.2, required=False, lift=4),
    # Membership Type — the form marks this "completed by a club officer".
    _check("mtn", 0, 315.3, 156.2, nudge=-6.0),
    _check("mtd", 0, 315.3, 177.7, nudge=-6.0),
    _check("mtr", 0, 315.3, 199.2, nudge=-6.0),
    _check("mtw", 0, 315.3, 220.7, nudge=-6.0),
    _check("mtt", 0, 315.3, 242.2, nudge=-6.0),
    # Gender.
    _check("gf", 0, 113.5, 381.8, nudge=-2.5, width=8.0),
    _check("gm", 0, 180.0, 381.8, nudge=-2.5, width=8.0),
    _check("go", 0, 239.9, 381.8, nudge=-2.5, width=8.0),
    # Membership fee by month of entry.
    _check("f1", 0, 315.3, 447.3, nudge=-6.0),
    _check("f2", 0, 315.3, 468.7, nudge=-6.0),
    _check("f3", 0, 315.3, 490.2, nudge=-6.0),
    _check("f4", 0, 315.3, 511.7, nudge=-6.0),
    _check("f5", 0, 315.3, 533.2, nudge=-6.0),
    _check("f6", 0, 315.3, 554.7, nudge=-6.0),
    # Preferable contact methods.
    _check("cm", 0, 36.0, 672.8, nudge=-5.0, width=9.0),
    _check("ce", 0, 108.0, 672.8, nudge=-5.0, width=9.0),
    _check("cp", 0, 171.3, 672.8, nudge=-5.0, width=9.0),
]

# --- page 2 -----------------------------------------------------------------
# 9pt and short ids across the sponsor row. Each slot is only ~126pt wide and a
# field is as wide as its tag, so "{textfield*:officer:sponsorlastname}" at 9pt
# ran 157pt and straight through the neighbour beside it — the four read as one
# continuous bar.
FIELDS += [
    _on_line("slast", 1, 36.0, 165.0, 110.2, required=False, lift=13, font_size=9),
    _on_line("sfirst", 1, 170.0, 299.0, 110.2, required=False, lift=13, font_size=9),
    _on_line("smem", 1, 304.0, 430.0, 110.2, required=False, lift=13, font_size=9),
    _on_line(
        "sclub",
        1,
        435.0,
        558.0,
        110.2,
        required=False,
        lift=13,
        font_size=9,
    ),
    # Verification of Applicant / of Club Officer. These two blocks are bare
    # labels with no printed line at all, which is why PandaDoc had nothing to
    # anchor to and why they were re-dragged by hand every time.
    # Short id so the date widget stays narrow: its width follows the tag's, and
    # at "signdate" it ran to x=156 and collided with the signature box at 140.
    _on_line("sd", 1, 36.0, 130.0, 716.0, kind=DATE),
    # Distinct optIds, not two "signature" tags. The role lives in the tag, so
    # unlike the field-name scheme this replaced, the id alone has to be unique —
    # PandaDoc keys the fields object by it, and a collision silently drops one.
    _on_line("asig", 1, 140.0, 260.0, 712.0, kind=SIGNATURE, font_size=9),
    # Both signatures are given the SAME 120pt slot at 9pt. A field is as wide as
    # its tag, so "officersign" padded to 200pt produced a visibly bigger box
    # than the applicant's — there was no reason for it beyond tag length. The
    # box's height follows its width, so a narrower tag is also what keeps it
    # from growing over the label beneath. Officer paragraph ends at 641.9, its
    # label sits at 707.2; the applicant's are 661.4 and 717.7.
    _on_line("osig", 1, 315.3, 435.3, 702.0, kind=SIGNATURE, font_size=9),
]

SPONSOR_FIELDS = {"slast", "sfirst", "smem", "sclub"}

# The sponsor line spans the full width, so the x-rule would split it between
# both signers. It is one block and the form marks it as the officer's.
FIELDS = [
    replace(spec, role=OFFICER) if spec.name in SPONSOR_FIELDS else spec
    for spec in FIELDS
]

# --- page 3 -----------------------------------------------------------------
FIELDS += [
    _check("cy", 2, 70.8, 573.0, nudge=-6.0),
    _check("cn", 2, 70.8, 624.3, nudge=-6.0),
    _on_line("consentemail", 2, 70.8, 327.1, 608.6, required=False, lift=4),
    _on_line("printedname", 2, 132.3, 362.3, 659.9, lift=4),
    # Moved right, into the empty half of the page, rather than onto the printed
    # "Signature" rule. Printed Name, Signature and Date sit 25pt apart here and
    # PandaDoc's signature box is around 55pt tall — on the rule it swallowed the
    # Printed Name field above it, and there is no baseline that avoids that.
    # Nothing on this page reaches past x=362 at these rows, so the box sits
    # beside them instead of on top of them.
    _on_line("psig", 2, 380.0, 500.0, 695.0, kind=SIGNATURE, font_size=9),
    _on_line("pd", 2, 96.0, 336.9, 711.2, kind=DATE, lift=4),
]


def _escape(text: str) -> str:
    for old, new in (("\\", r"\\"), ("(", r"\("), (")", r"\)")):
        text = text.replace(old, new)
    return text


def tag_width(spec: FieldSpec) -> float:
    """How wide the tag actually is, which is how wide the field will be."""
    return _text_width(spec.tag(), spec.size())


def overflows(spec: FieldSpec, page_width: float) -> bool:
    """A tag running past the page edge is one PandaDoc may not place at all."""
    return spec.x + tag_width(spec) > page_width


def _content(specs: list[FieldSpec], page_height: float, visible: bool) -> bytes:
    """A content stream drawing every tag for one page, in white.

    White, and NOT text rendering mode 3. Mode 3 leaves the glyphs in the text
    layer while painting nothing, which reads like a tidier way to hide a tag —
    and it is what an upload with zero fields was traced back to. PandaDoc's
    instruction is precise: *"match the font color of the field tags with the
    document's background color"*. It wants text that is drawn and happens to be
    invisible, not text that is skipped at draw time. pypdf can still extract
    mode 3 text, so the PDF looked correct locally while PandaDoc saw nothing.

    The cost is that white glyphs paint over anything beneath them, so tags are
    positioned to sit in the form's whitespace — see _check, which lifts
    checkbox tags into the gap above their row rather than across their label.

    ``visible`` switches to red, for the preview script.
    """
    parts = ["q"]

    # Erase the printed circles first, so the PandaDoc checkbox that replaces
    # each one is not sitting next to a leftover glyph.
    parts.append("1 1 1 rg")
    for spec in specs:
        if spec.erase is None:
            continue
        x0, top, x1, bottom = spec.erase
        parts.append(
            f"{x0:.2f} {page_height - bottom:.2f} {x1 - x0:.2f} {bottom - top:.2f} re f"
        )

    parts += ["1 0 0 rg" if visible else "1 1 1 rg", "0 Tr"]
    for spec in specs:
        parts.append("BT")
        parts.append(f"/CBTHelv {spec.size():.1f} Tf")
        parts.append(f"1 0 0 1 {spec.x:.2f} {page_height - spec.baseline:.2f} Tm")
        parts.append(f"({_escape(spec.tag())}) Tj")
        parts.append("ET")
    parts.append("Q")
    return ("\n".join(parts)).encode("latin-1")


def bank_values() -> list[tuple[str, float, str]]:
    """The bank block to draw: (label, baseline, value), from the environment.

    An unset or empty variable keeps the placeholder rather than drawing a blank
    line, so a misconfigured build produces a form that is visibly wrong instead
    of one that is quietly incomplete.
    """
    return [
        (env, y, os.getenv(env, "").strip() or placeholder)
        for env, y, placeholder in BANK_ROWS
    ]


def _bank_content() -> bytes:
    """The content stream for the bank block, in black at the source's size."""
    parts = ["q", "0 g", "0 Tr"]
    for _, baseline, value in bank_values():
        parts.append("BT")
        parts.append(f"/CBTHelv {BANK_VALUE_SIZE:.1f} Tf")
        parts.append(f"1 0 0 1 {BANK_VALUE_X:.2f} {baseline:.2f} Tm")
        parts.append(f"({_escape(value)}) Tj")
        parts.append("ET")
    parts.append("Q")
    return ("\n".join(parts)).encode("latin-1")


def _draw(
    writer: PdfWriter, page_number: int, specs: list[FieldSpec], visible: bool
) -> None:
    """Append the tag content stream to a page, and register the font."""
    page = writer.pages[page_number]

    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
    )
    resources = page.setdefault(NameObject("/Resources"), DictionaryObject())
    fonts = resources.setdefault(NameObject("/Font"), DictionaryObject())
    fonts[NameObject("/CBTHelv")] = font

    # Merge into ONE content stream rather than appending a second to the page's
    # /Contents array. Both are valid PDF and every local extractor read either,
    # but an upload whose tags were in an appended stream came back with zero
    # fields and no error — consistent with a parser that reads only the first
    # stream on a page. PandaDoc's own advice for tags that fail to place is to
    # flatten the PDF; this is that, at the point where the file is written.
    existing = page.raw_get("/Contents").get_object()
    if isinstance(existing, ArrayObject):
        original = b"\n".join(part.get_object().get_data() for part in existing)
    else:
        original = existing.get_data()

    addition = _content(specs, float(page.mediabox.height), visible)
    if page_number == BANK_PAGE:
        # Same stream, for the same reason: an appended second stream is valid
        # PDF that PandaDoc did not read.
        addition += b"\n" + _bank_content()

    merged = DecodedStreamObject()
    merged.set_data(original + b"\n" + addition)
    page[NameObject("/Contents")] = writer._add_object(merged)


def collisions(specs: list[FieldSpec]) -> list[tuple[FieldSpec, FieldSpec]]:
    """Pairs of fields on the same row whose boxes would overlap.

    A field is as wide as its tag, which is easy to forget when the tag is long
    and the slot is narrow. The four sponsor fields each got a tag half again as
    wide as its slot and rendered as one continuous bar across the page.
    """
    found = []
    for i, a in enumerate(specs):
        for b in specs[i + 1 :]:
            if a.page != b.page or abs(a.baseline - b.baseline) > 6.0:
                continue
            if a.x < b.x + tag_width(b) and b.x < a.x + tag_width(a):
                found.append((a, b))
    return found


def _assert_unique(specs: list[FieldSpec]) -> None:
    """Two tags sharing an optId collapse into one entry in the fields object.

    PandaDoc then places only one of them, and reports nothing.
    """
    seen: dict[str, FieldSpec] = {}
    for spec in specs:
        clash = seen.get(spec.name)
        if clash is not None:
            raise ValueError(
                f"duplicate optId {spec.name!r}: page {clash.page + 1} and "
                f"page {spec.page + 1}"
            )
        seen[spec.name] = spec


def build(destination: Path = OUTPUT, visible: bool = False) -> list[FieldSpec]:
    """Write the tagged PDF and return the fields it now carries.

    ``visible`` draws the tags in red instead of invisibly, which is the only
    way to see where they land — see scripts/preview_form_fields.py.
    """
    _assert_unique(FIELDS)
    writer = PdfWriter(clone_from=str(SOURCE))
    for page_number in range(len(writer.pages)):
        on_page = [spec for spec in FIELDS if spec.page == page_number]
        if on_page:
            _draw(writer, page_number, on_page, visible)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        writer.write(handle)
    return FIELDS


def write_manifest(specs: list[FieldSpec]) -> None:
    """Emit the generated manifest the tests and the runtime read."""
    rows = "\n".join(
        f'    ("{spec.name}", "{spec.resolved_role()}", "{spec.kind}", '
        f"{spec.required}),"
        for spec in specs
    )
    MANIFEST.write_text(
        '"""The application form\'s fields. Generated — do not edit.\n'
        "\n"
        "Regenerate with::\n"
        "\n"
        "    uv run python scripts/build_form_fields.py\n"
        "\n"
        "Each row is (optId, role, type, required). The roles are carried by the\n"
        "field tags drawn into the PDF, so the API does not need to assign them;\n"
        "this exists so the tests can check the artefact without a PDF parser,\n"
        "and so a human can see what the form asks for without opening it.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "FIELDS: tuple[tuple[str, str, str, bool], ...] = (\n"
        f"{rows}\n"
        ")\n"
        "\n"
        "FIELD_NAMES: tuple[str, ...] = tuple(name for name, _, _, _ in FIELDS)\n"
    )


def main() -> int:
    specs = build()
    write_manifest(specs)

    print(f"wrote {OUTPUT.relative_to(REPO)}")
    print(f"wrote {MANIFEST.relative_to(REPO)}")
    print(f"{len(specs)} field tags")
    for role in (APPLICANT, OFFICER):
        owned = [s for s in specs if s.resolved_role() == role]
        needed = [s for s in owned if s.required]
        print(f"  {role}: {len(owned)} ({len(needed)} required)")
    print("\ndates and signatures:")
    for spec in specs:
        if spec.kind in (DATE, SIGNATURE):
            print(f"  {spec.tag()}")

    # A tag wider than the field it marks makes PandaDoc place an oversized
    # field; one that runs off the page may not be placed at all.
    from pypdf import PdfReader

    widths = [float(p.mediabox.width) for p in PdfReader(str(SOURCE)).pages]
    clashes = collisions(specs)
    if clashes:
        print("\nOVERLAPPING FIELDS — these will run into each other:")
        for a, b in clashes:
            print(f"  page {a.page + 1}  {a.name} x {b.name}")

    over = [s for s in specs if overflows(s, widths[s.page])]
    wide = [s for s in specs if tag_width(s) > s.width * 1.35 and s not in over]
    if over:
        print("\nRUNS OFF THE PAGE — these will not place correctly:")
        for spec in over:
            print(f"  page {spec.page + 1}  {spec.tag()}")
    if wide:
        print("\nwider than the field it marks (field will be oversized):")
        for spec in wide:
            print(
                f"  page {spec.page + 1}  {tag_width(spec):5.0f}pt vs "
                f"{spec.width:5.0f}pt  {spec.tag()}"
            )
    return 1 if (over or clashes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
