"""Run the membership draft workflow once, locally, without a server.

    uv run python scripts/run_locally.py

Reads configuration from ``.env``. Keep ``DRY_RUN=true`` there until you have
seen the quotes it produces: a dry run reads the real sheet and renders the real
emails, but creates no draft, writes no cell and posts nothing to Slack.

This runs the workflow directly, without starting a web server. The server
exists only because Cloud Scheduler can do nothing but make an HTTP request;
locally you do not need it.
"""

from __future__ import annotations

import sys
from dataclasses import asdict

from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    from clubops.observability import setup_logging

    setup_logging()

    # Imported after load_dotenv so configuration is present.
    from clubops.config import ConfigError
    from clubops.jobs import run_membership_draft_job

    try:
        summary = run_membership_draft_job(trace_id="local")
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        print("check .env against .env.example", file=sys.stderr)
        return 2

    print(f"\n{asdict(summary)}")
    if summary.dry_run:
        print("DRY_RUN was on: nothing was drafted, marked or posted.")
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
