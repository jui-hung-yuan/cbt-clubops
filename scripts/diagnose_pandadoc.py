"""Upload the form and report exactly what PandaDoc made of it.

    uv run python scripts/diagnose_pandadoc.py --email you@example.com

Creating a document succeeds whether or not PandaDoc parsed a single field tag.
It returns 201, the document reaches document.draft, and the form comes out
blank with nothing anywhere saying why. This asks the question the create call
does not answer: which fields actually exist on the finished document.

It ignores DRY_RUN — the whole point is to make a real one. Delete the documents
it leaves behind.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", default="Diagnostic Upload")
    parser.add_argument("--email", required=True, help="any address you control")
    parser.add_argument(
        "--dump", action="store_true", help="print every field PandaDoc created"
    )
    parser.add_argument(
        "--document-id",
        help="inspect an existing document instead of creating one. Costs no "
        "upload, and is how to look again at a document you already made.",
    )
    parser.add_argument(
        "--editor-ver",
        default="",
        help="pass editor_ver to the upload (ev1 = Classic editor). Field tags "
        "predate the current editor; this tests whether that is why they are "
        "ignored.",
    )
    args = parser.parse_args()

    load_dotenv()
    from clubops.observability import setup_logging

    setup_logging()

    from clubops.config import ConfigError, load_settings
    from clubops.domain.application_fields import FIELDS as TAGGED
    from clubops.integrations.pandadoc import (
        PandaDocApplicationCreator,
        PandaDocError,
        build_document_payload,
    )

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    if not settings.pandadoc.api_key:
        print("PANDADOC_API_KEY is not set", file=sys.stderr)
        return 2

    creator = PandaDocApplicationCreator(
        api_key=settings.pandadoc.api_key,
        officer_email=settings.pandadoc.officer_email,
        officer_name=settings.pandadoc.officer_name,
        editor_ver=args.editor_ver,
    )

    if args.document_id:
        _report(creator, args.document_id, TAGGED, dump=True)
        return 0

    payload = build_document_payload(
        args.name,
        args.email,
        settings.pandadoc.officer_email,
        settings.pandadoc.officer_name,
    )
    print("--- request ---")
    print(f"parse_form_fields : {payload['parse_form_fields']}")
    print(f"recipients        : {[r['role'] for r in payload['recipients']]}")
    print(f"fields declared   : {len(payload.get('fields', {}))}")
    print(f"tags in the PDF   : {len(TAGGED)}")

    print(f"editor_ver        : {args.editor_ver or '(default)'}")
    try:
        document_id = creator.create_application_document(args.name, args.email)
    except PandaDocError as exc:
        print(f"\nupload failed: {exc}", file=sys.stderr)
        return 1

    _report(creator, document_id, TAGGED, dump=args.dump)
    return 0


def _report(creator, document_id: str, tagged, dump: bool) -> None:
    """Print what PandaDoc made of the tags, from the details endpoint."""
    from clubops.integrations.pandadoc import document_link

    placed = creator.placed_fields(document_id)

    print("\n--- what PandaDoc built ---")
    print(f"document          : {document_link(document_id)}")
    print(f"fields placed     : {len(placed)}")

    if not placed:
        print(
            "\nNo fields. The tags were not parsed. The document was still\n"
            "created and reported success, which is why this is invisible\n"
            "without asking.\n"
        )
        return

    by_type = Counter(field.get("type", "?") for field in placed)
    print(f"by type           : {dict(by_type)}")

    # PandaDoc mints its own field_id; our optId comes back as "name" and
    # "merge_field". Signature fields have no merge field, hence the difference.
    ours = {name for name, _, _, _ in tagged}
    got = {field.get("name") for field in placed}
    missing = sorted(ours - got)
    print(f"our ids matched   : {len(ours & got)}/{len(ours)}")
    if missing:
        print(f"MISSING           : {', '.join(missing)}")

    # "required" is not reported by this endpoint at all — check it in the UI.
    # Assignment is, via assigned_to, so that much can be verified from here.
    recipients = Counter(
        (field.get("assigned_to") or {}).get("email", "unassigned") for field in placed
    )
    print(f"assigned to       : {dict(recipients)}")
    unassigned = [f for f in placed if not f.get("assigned_to")]
    if unassigned:
        print(f"UNASSIGNED        : {len(unassigned)}")

    expected = Counter(role for _, role, _, _ in tagged)
    print(f"expected per role : {dict(expected)}")
    print("\nNote: required is not returned by this endpoint. Check it in the UI.")

    if dump:
        print("\n--- first three fields, raw ---")
        print(json.dumps(placed[:3], indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
