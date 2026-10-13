"""Request log lines carry error_code and the JSON formatter lets it through."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.app import create_app
from app.core.config import Settings
from app.core.logging import JsonFormatter


def test_request_completed_has_the_error_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    client = TestClient(create_app(Settings()))

    client.get("/api/v1/nope")
    client.get("/api/v1/me")

    completed = [r for r in caplog.records if r.getMessage() == "request_completed"]
    assert [r.error_code for r in completed] == ["NOT_FOUND", "AUTH_REQUIRED"]  # type: ignore[attr-defined]
    payload = json.loads(JsonFormatter().format(completed[0]))
    assert payload["error_code"] == "NOT_FOUND"
    assert payload["status_code"] == 404


def test_csrf_rejection_is_logged_with_origin_and_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    client = TestClient(create_app(Settings()))
    client.cookies.set("lottery_passport_session", "token")

    response = client.post("/api/v1/auth/logout", headers={"Origin": "http://x.test"})

    assert response.status_code == 403
    record = next(r for r in caplog.records if r.getMessage() == "csrf_rejected")
    assert record.origin == "http://x.test"  # type: ignore[attr-defined]
    assert "X-Requested-With" in record.reason  # type: ignore[attr-defined]
