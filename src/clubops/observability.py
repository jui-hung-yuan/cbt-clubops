"""Logging setup.

Without this the service is silent in production: uvicorn configures its own
loggers but not the root logger, so ``logger.info(...)`` calls elsewhere in the
package go nowhere. A scheduled job you cannot see the output of is a job you
cannot debug at 23:00 on a Saturday.

On Cloud Run this attaches the Cloud Logging handler, which stamps each record
with the request's trace id. That is what makes the "open the logs for this run"
link in the Slack failure message actually resolve to the right run.
"""

from __future__ import annotations

import logging
import os

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure logging once, appropriately for the environment."""
    global _configured
    if _configured:
        return
    _configured = True

    on_cloud_run = bool(os.getenv("K_SERVICE"))

    if on_cloud_run:
        try:
            import google.cloud.logging

            client = google.cloud.logging.Client()
            client.setup_logging(log_level=level)
            logging.getLogger(__name__).info("cloud logging handler attached")
            return
        except Exception:
            # Never let telemetry setup stop the job from running. Fall through
            # to stdout, which Cloud Run captures anyway (without trace ids).
            logging.basicConfig(level=level, force=True)
            logging.getLogger(__name__).exception(
                "cloud logging unavailable; falling back to stdout"
            )
            return

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        force=True,
    )
