"""Create one membership application document in PandaDoc, locally.

    uv run python scripts/create_application_doc.py \
        --name "Ada Lovelace" --email ada@example.com

Reads configuration from ``.env``; needs PANDADOC_API_KEY. Honours DRY_RUN,
which validates the request and prints what would be created without uploading
anything — worth using first, because a created document is a real object in
the PandaDoc workspace that then has to be deleted by hand.

The document is left in draft. Nothing here sends it; open the printed link,
check it, and send it yourself.
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True, help="the guest's full name")
    parser.add_argument("--email", required=True, help="the guest's email address")
    args = parser.parse_args()

    load_dotenv()
    from clubops.observability import setup_logging

    setup_logging()

    # Imported after load_dotenv so configuration is present.
    from clubops.config import ConfigError
    from clubops.integrations.pandadoc import PandaDocError
    from clubops.jobs import run_application_document_job

    try:
        result = run_application_document_job(
            guest_name=args.name, guest_email=args.email, trace_id="local"
        )
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        print("check .env against .env.example", file=sys.stderr)
        return 2
    except (PandaDocError, ValueError) as exc:
        print(f"could not create the document: {exc}", file=sys.stderr)
        return 1

    if result["dry_run"] == "true":
        print("\nDRY_RUN was on: nothing was uploaded.")
        print(f"would have created: {result['name']}")
        return 0

    print(f"\n{result['name']}")
    print(result["link"])
    print("\ndraft — review it and send it yourself")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
