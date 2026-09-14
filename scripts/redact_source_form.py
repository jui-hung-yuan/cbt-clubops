"""Remove the club's bank details from the source application form.

Run once, by hand, to produce the form that is committed to this repository.

The club's PDF has the treasurer's IBAN, BIC, bank and name printed on page 1.
That is a named person's bank account, and this repository is public, so the
committed source has that column emptied. ``build_form_fields.py`` draws the
values back in — placeholders by default, the real ones at image build time.

**Covering the text with a white rectangle is not redaction.** The glyphs stay in
the content stream and ``extract_text`` returns them — the same fact that makes
the white field tags work is what would make a white box useless here. So this
removes the text-showing operators themselves.

    uv run python scripts/redact_source_form.py \
        --source ~/private/CBT_application_form_2026_fees_v2.pdf

The original is not in this repository and must not be added to it. Keep it
wherever the club keeps its documents.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO / "src" / "clubops" / "assets" / "CBT_application_form_2026_fees_v2.pdf"
)

# The value column of the bank block on page 1. Labels ("IBAN:", "BIC:", ...)
# sit at x=315 and stay; the values sit at x=373-428. The band stops above the
# Reference row at y=84.7, which reads "CBT fees + Your Name" and is instruction
# text rather than anyone's data.
REDACT_PAGE = 0
REDACT_X_MIN = 360.0
REDACT_Y_MIN = 95.0
REDACT_Y_MAX = 150.0

SHOW_TEXT = {"Tj", "TJ", "'", '"'}


def _redact_page(page, reader) -> list[str]:
    """Drop every text-showing operator inside the redaction rectangle.

    Returns what was removed, so the caller can print it and a human can confirm
    the right thing went.
    """
    content = ContentStream(page.get_contents(), reader)
    kept: list[tuple[list, bytes]] = []
    removed: list[str] = []

    # Text position lives in two matrices: Tm sets both, Td/TD/T* move the line
    # matrix and reset the text matrix to it. Only e and f (indexes 4 and 5)
    # matter here, so the rest is carried but never used.
    tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    tlm = list(tm)
    leading = 0.0

    for operands, operator in content.operations:
        op = operator.decode() if isinstance(operator, bytes) else str(operator)

        if op == "BT":
            tm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            tlm = list(tm)
        elif op == "Tm":
            tlm = [float(v) for v in operands]
            tm = list(tlm)
        elif op in {"Td", "TD"}:
            tx, ty = float(operands[0]), float(operands[1])
            if op == "TD":
                leading = -ty
            tlm[4] += tx
            tlm[5] += ty
            tm = list(tlm)
        elif op == "TL":
            leading = float(operands[0])
        elif op == "T*":
            tlm[5] -= leading
            tm = list(tlm)

        if op in SHOW_TEXT and tm[4] >= REDACT_X_MIN and REDACT_Y_MIN <= tm[5] <= REDACT_Y_MAX:
            removed.append(f"  x={tm[4]:6.1f} y={tm[5]:6.1f}  {operands!r:.90}")
            continue

        kept.append((operands, operator))

    content.operations = kept
    page.replace_contents(content)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="the club's original PDF, from outside this repository",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.source.exists():
        print(f"no such file: {args.source}", file=sys.stderr)
        return 2

    reader = PdfReader(str(args.source))
    writer = PdfWriter(clone_from=str(args.source))

    removed = _redact_page(writer.pages[REDACT_PAGE], reader)
    if not removed:
        print(
            "nothing was removed — check the coordinates against the source",
            file=sys.stderr,
        )
        return 1

    print(f"removed {len(removed)} text operations from page {REDACT_PAGE + 1}:")
    print("\n".join(removed))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    writer.write(str(args.output))
    print(f"\nwrote {args.output.relative_to(REPO)}")

    leaked = _still_present(args.output)
    if leaked:
        print(f"\nSTILL EXTRACTABLE: {leaked}", file=sys.stderr)
        return 1
    print("verified: no bank values extractable from the result")
    return 0


def _still_present(path: Path) -> list[str]:
    """Extract the result and look for anything that should have gone."""
    text = "".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
    compact = "".join(text.split())
    # Bank-shaped rather than this club's values: a script whose job is removing
    # an IBAN should not have one written inside it.
    return [
        match
        for match in re.findall(r"DE\d{2}\d{18}|[A-Z]{4}DE[A-Z0-9]{2,5}", compact)
        if not match.startswith(("DE00", "XXXXDE"))
    ]


if __name__ == "__main__":
    raise SystemExit(main())
