"""The Cloud Scheduler entry point."""

from __future__ import annotations

from unittest import mock

import pytest
from fastapi.testclient import TestClient

from clubops import web
from clubops.pipeline import RunSummary


@pytest.fixture
def client():
    return TestClient(web.app)


def test_healthcheck_reports_ok(client):
    response = client.get("/healthcheck")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_job_route_returns_a_summary(client):
    summary = RunSummary(processed=2, skipped=1, failed=0, dry_run=False)
    with mock.patch.object(web, "run_membership_draft_job", return_value=summary):
        response = client.post("/jobs/membership-drafts")

    assert response.status_code == 200
    assert response.json() == {
        "processed": 2,
        "skipped": 1,
        "failed": 0,
        "dry_run": False,
    }


def test_row_failures_still_return_200(client):
    """Cloud Scheduler must not retry a partially-completed batch: retrying
    would create duplicate drafts for the guests already handled."""
    summary = RunSummary(processed=1, skipped=0, failed=2, dry_run=False)
    with mock.patch.object(web, "run_membership_draft_job", return_value=summary):
        response = client.post("/jobs/membership-drafts")

    assert response.status_code == 200
    assert response.json()["failed"] == 2


def test_the_trace_id_is_taken_from_the_cloud_run_header(client):
    summary = RunSummary(processed=0, skipped=0, failed=0, dry_run=False)
    with mock.patch.object(
        web, "run_membership_draft_job", return_value=summary
    ) as job:
        client.post(
            "/jobs/membership-drafts",
            headers={"X-Cloud-Trace-Context": "abc123def456/9876543210;o=1"},
        )

    job.assert_called_once_with(trace_id="abc123def456")


# --- the application document route ---------------------------------------


def test_the_application_route_returns_the_link(client):
    """The link is the whole point: a human opens it, checks it, sends it."""
    result = {
        "document_id": "abc123",
        "link": "https://app.pandadoc.com/a/#/documents/abc123",
        "name": "CBT Membership Application — Ada Lovelace",
        "dry_run": "false",
    }
    with mock.patch.object(
        web, "run_application_document_job", return_value=result
    ) as job:
        response = client.post(
            "/jobs/application-document",
            json={"name": "Ada Lovelace", "email": "ada@example.com"},
        )

    assert response.status_code == 200
    assert response.json()["link"].endswith("abc123")
    job.assert_called_once_with(
        guest_name="Ada Lovelace", guest_email="ada@example.com", trace_id=""
    )


def test_the_application_route_requires_a_name_and_email(client):
    """There are only two inputs; neither is optional."""
    response = client.post("/jobs/application-document", json={"name": "Ada Lovelace"})
    assert response.status_code == 422


def test_the_application_route_passes_the_trace_id(client):
    result = {"document_id": "x", "link": "", "name": "", "dry_run": "false"}
    with mock.patch.object(
        web, "run_application_document_job", return_value=result
    ) as job:
        client.post(
            "/jobs/application-document",
            json={"name": "Ada Lovelace", "email": "ada@example.com"},
            headers={"X-Cloud-Trace-Context": "trace9/1;o=1"},
        )

    assert job.call_args.kwargs["trace_id"] == "trace9"
