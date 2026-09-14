"""PandaDoc adapter — uploads the application form and leaves it in draft.

There is deliberately no method here that sends a document for signature. The
``/send`` endpoint does not appear anywhere in this module, so no bug elsewhere
in the service can reach it. A human opens the draft in PandaDoc, checks it, and
sends it themselves — the same rule the Gmail adapter follows.

Why the PDF is uploaded on every call rather than stored once as a PandaDoc
template: PandaDoc's "create template from file upload" endpoint supports
neither form fields nor field tags, so a stored template cannot carry the field
placement that is the whole point of this feature. The tagged PDF in
``assets/`` is the template; PandaDoc holds no copy.

Field roles ride in the tags themselves, but the request must still declare
every tag's optId in its ``fields`` object — PandaDoc drops any tag that is not
declared there, without reporting it.

Uses raw httpx rather than the PandaDoc SDK; two calls with a dependency
already in the tree is not worth another package.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from clubops.domain.application_form import (
    APPLICANT_ROLE,
    OFFICER_ROLE,
    build_field_assignments,
    document_name,
    split_name,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.pandadoc.com/public/v1"
CREATE_URL = f"{BASE_URL}/documents"
DOCUMENT_URL = f"{BASE_URL}/documents/{{document_id}}"
DETAILS_URL = f"{BASE_URL}/documents/{{document_id}}/details"
APP_URL = "https://app.pandadoc.com/a/#/documents/{document_id}"

FORM_PDF = (
    Path(__file__).resolve().parent.parent
    / "assets"
    / ("cbt_application_form_fields.pdf")
)

# PandaDoc processes an uploaded file in the background: the document is created
# as document.uploaded and only becomes editable at document.draft.
UPLOADED_STATUS = "document.uploaded"
DRAFT_STATUS = "document.draft"
ERROR_STATUS = "document.error"


class PandaDocError(RuntimeError):
    """Raised when PandaDoc rejects a request or fails to process a document."""


def build_document_payload(
    guest_name: str, guest_email: str, officer_email: str, officer_name: str
) -> dict:
    """Build the JSON half of the multipart create-document request."""
    if not guest_email.strip():
        raise ValueError("cannot create a document without a recipient email")
    first_name, last_name = split_name(guest_name)
    officer_first, officer_last = split_name(officer_name)
    return {
        "name": document_name(guest_name),
        "recipients": [
            {
                "email": guest_email.strip(),
                "first_name": first_name,
                "last_name": last_name,
                "role": APPLICANT_ROLE,
                "signing_order": 1,
            },
            {
                "email": officer_email,
                "first_name": officer_first,
                "last_name": officer_last,
                "role": OFFICER_ROLE,
                "signing_order": 2,
            },
        ],
        # False means "read field tags", which is what the PDF carries. The
        # form-field path cannot express required or date fields — PandaDoc
        # documents auto-placed fields as "not required" by default — and the
        # two paths are mutually exclusive: a file with both produces duplicate,
        # overlapping fields.
        "parse_form_fields": False,
        # Required even though the tags already carry role and type: PandaDoc
        # will not place a tag whose optId is missing here, and says nothing
        # about it. See build_field_assignments.
        "fields": build_field_assignments(),
    }


class PandaDocApplicationCreator:
    """Creates an application document in draft for a human to review and send."""

    def __init__(
        self,
        api_key: str,
        officer_email: str,
        officer_name: str,
        timeout: float = 30.0,
        poll_attempts: int = 8,
        poll_interval: float = 2.0,
        editor_ver: str = "",
    ) -> None:
        self._api_key = api_key
        self._officer_email = officer_email
        self._officer_name = officer_name
        self._timeout = timeout
        self._poll_attempts = poll_attempts
        self._poll_interval = poll_interval
        # "ev1" selects PandaDoc's Classic editor. Left empty normally; it is a
        # lever for diagnosing tag parsing, since the tag mechanism predates the
        # current editor and the two may not treat an upload identically.
        self._editor_ver = editor_ver

    @property
    def _headers(self) -> dict[str, str]:
        # PandaDoc uses "API-Key", not "Bearer". A Bearer prefix fails with a
        # 401 that reads like a bad key.
        return {"Authorization": f"API-Key {self._api_key}"}

    def create_application_document(self, guest_name: str, guest_email: str) -> str:
        """Upload the form, wait for processing, and return the document id."""
        payload = build_document_payload(
            guest_name, guest_email, self._officer_email, self._officer_name
        )
        if not FORM_PDF.exists():
            raise PandaDocError(
                f"the annotated form is missing at {FORM_PDF}; "
                "run scripts/build_form_fields.py"
            )

        with FORM_PDF.open("rb") as handle:
            response = httpx.post(
                CREATE_URL,
                headers=self._headers,
                params={"editor_ver": self._editor_ver} if self._editor_ver else None,
                files={"file": (FORM_PDF.name, handle, "application/pdf")},
                data={"data": json.dumps(payload)},
                timeout=self._timeout,
            )

        if response.status_code == 429:
            raise PandaDocError(
                "PandaDoc rate-limited the upload (429). A sandbox key allows "
                "10 requests a minute, a production key 300 — wait a minute and "
                "try again."
            )
        if response.status_code >= 400:
            raise PandaDocError(
                f"PandaDoc rejected the upload ({response.status_code}): "
                f"{response.text[:500]}"
            )
        created = response.json()
        document_id = created.get("id")
        if not document_id:
            raise PandaDocError(f"PandaDoc returned no document id: {created!r}")

        # PandaDoc reports tag problems here rather than by failing the request.
        # A document with no fields is created successfully and says nothing, so
        # anything it does say is worth keeping.
        if created.get("info_message"):
            logger.info("PandaDoc says: %s", created["info_message"])
        logger.debug("create response: %s", json.dumps(created)[:2000])

        logger.info("created document %s for %s", document_id, guest_email)
        self._await_draft(str(document_id))
        return str(document_id)

    def placed_fields(self, document_id: str) -> list[dict]:
        """What PandaDoc actually made of the tags.

        The only reliable answer to "did the tags parse". Creation succeeds
        either way, so this is what distinguishes a working upload from a
        document that merely looks like one.
        """
        response = httpx.get(
            DETAILS_URL.format(document_id=document_id),
            headers=self._headers,
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            logger.warning(
                "could not read document details (%s): %s",
                response.status_code,
                response.text[:300],
            )
            return []
        return response.json().get("fields", [])

    def _await_draft(self, document_id: str) -> None:
        """Poll until the upload finishes processing.

        Backs off between checks rather than polling at a fixed interval. A
        sandbox key allows only 10 requests a minute — one every six seconds —
        so a tight loop burns the whole budget and fails with a 429 that reads
        like a broken upload. Processing usually finishes within the first two
        checks anyway; the backoff only costs anything when it does not.
        """
        url = DOCUMENT_URL.format(document_id=document_id)
        wait = self._poll_interval
        for attempt in range(self._poll_attempts):
            response = httpx.get(url, headers=self._headers, timeout=self._timeout)
            if response.status_code == 429:
                # Retry-After is authoritative when present; the fallback keeps
                # us under the sandbox's one-per-six-seconds even without it.
                retry_after = float(response.headers.get("Retry-After", 0) or 0)
                time.sleep(max(retry_after, 6.0))
                continue
            response.raise_for_status()
            status = response.json().get("status", "")
            if status == DRAFT_STATUS:
                logger.info("document %s is ready to review", document_id)
                return
            if status == ERROR_STATUS:
                raise PandaDocError(f"PandaDoc failed to process {document_id}")
            if status != UPLOADED_STATUS:
                # Anything else means somebody moved it on already; not our call
                # to override, and definitely not ours to send.
                logger.warning("document %s has status %s", document_id, status)
                return
            if attempt < self._poll_attempts - 1:
                time.sleep(wait)
                wait = min(wait * 1.6, 12.0)
        raise PandaDocError(
            f"document {document_id} was still processing after "
            f"{self._poll_attempts} checks"
        )


def document_link(document_id: str) -> str:
    """The URL a human opens to review the draft."""
    return APP_URL.format(document_id=document_id)
