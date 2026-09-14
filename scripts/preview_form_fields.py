"""Render the form with its field tags made visible, to check where they land.

    uv run python scripts/preview_form_fields.py

This is the cheap loop. In the real artefact the tags are invisible, so the only
way to see them is to build a second copy with them drawn in red.

What this can and cannot tell you:

- It **can** show that every tag sits on the right line, in the right column,
  and does not run into the form's own text or off the page.
- It **cannot** show what PandaDoc makes of them. A tag is replaced by a field
  whose width and font size PandaDoc derives from the tag; only a real upload
  shows the result. That is the trade the tag approach makes in exchange for
  required fields and date pickers, which native PDF form fields cannot carry.

Rendering goes through pdfium (via pypdfium2) rather than poppler, which is not
installed here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pypdfium2 as pdfium

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_form_fields import CHECKBOX, FIELDS, build

SCALE = 2.0


def main() -> int:
    out_dir = Path(
        os.environ.get("PREVIEW_DIR")
        or Path(__file__).resolve().parent.parent / "build" / "form-preview"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    # Two renders. "tags" shows where the tags sit; "clean" is the real
    # artefact, where the tags are white — and white paints, so this is the one
    # that shows whether a tag has chewed a hole in the form underneath it.
    for label, visible in (("tags", True), ("clean", False)):
        source = out_dir / f"{label}.pdf"
        build(destination=source, visible=visible)
        document = pdfium.PdfDocument(str(source))
        for page_number, page in enumerate(document):
            image = page.render(scale=SCALE).to_pil().convert("RGB")
            target = out_dir / f"{label}-page{page_number + 1}.png"
            image.save(target)
            print(f"wrote {target}")

    checkboxes = [spec for spec in FIELDS if spec.kind == CHECKBOX]
    print(
        f"\n{len(FIELDS)} tags drawn ({len(checkboxes)} checkboxes, at a smaller size)"
    )
    print("Check: every tag on its own line, none running into the form's own text.")
    print("Widest tags:")
    for spec in sorted(FIELDS, key=lambda s: -len(s.tag()))[:5]:
        print(f"  page {spec.page + 1}  x={spec.x:6.1f}  {spec.tag()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
