"""HTTP entry point.

Cloud Scheduler cannot run code — the only thing it can do when it fires is
make an HTTP request. This is the thing that receives it.

One route does the work. The rest of the service is a health check.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from clubops.jobs import run_application_document_job, run_membership_draft_job
from clubops.observability import setup_logging

load_dotenv()
setup_logging()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="cbt-clubops",
    description="Drafts Center Berlin Toastmasters membership emails for review.",
)


class ApplicationRequest(BaseModel):
    """The whole input: everything else on the form is filled in by a human."""

    name: str
    email: str


def _trace_id(request: Request) -> str:
    """Extract the trace id from Cloud Run's X-Cloud-Trace-Context header.

    Format is TRACE_ID/SPAN_ID;o=1. Used to link the Slack failure notice to
    the logs for that specific run.
    """
    header = request.headers.get("X-Cloud-Trace-Context", "")
    return header.split("/", 1)[0] if header else ""


@app.get("/healthcheck")
def healthcheck() -> dict[str, str]:
    """Liveness check.

    Deliberately not "/healthz": Google's frontend reserves that path on Cloud
    Run and answers it itself with a 404, before the request ever reaches the
    container. Every other path correctly returns 403 when unauthenticated.
    """
    return {"status": "ok"}


@app.post("/jobs/membership-drafts")
def membership_drafts(request: Request) -> JSONResponse:
    """Run the membership draft workflow once.

    Returns 200 even when individual rows failed. Cloud Scheduler treats a
    non-2xx as a failed attempt, and retrying a partially-completed batch would
    create duplicate Gmail drafts for the guests already handled. Row failures
    are reported to Slack instead, as they were in n8n.

    A 5xx is reserved for a failure before any row was touched — currently only
    a bad configuration or an unreadable sheet.
    """
    summary = run_membership_draft_job(trace_id=_trace_id(request))
    logger.info("membership draft run finished: %s", asdict(summary))
    return JSONResponse(status_code=200, content=asdict(summary))


@app.post("/jobs/application-document")
def application_document(request: Request, body: ApplicationRequest) -> JSONResponse:
    """Create one membership application document in PandaDoc, in draft.

    Unlike the draft job this is not on a schedule — it is called by hand once a
    guest has paid and wants to join. It never sends the document; the link it
    returns is for a human to review and send.

    A failure here returns 5xx on purpose. There is exactly one document at
    stake and no partial batch to duplicate, so the caller should see the error.
    """
    result = run_application_document_job(
        guest_name=body.name,
        guest_email=body.email,
        trace_id=_trace_id(request),
    )
    logger.info("application document run finished: %s", result)
    return JSONResponse(status_code=200, content=result)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
