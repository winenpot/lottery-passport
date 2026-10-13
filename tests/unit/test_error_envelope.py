"""Every error, including the framework's own, uses {"error": {code, message}}."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.app import create_app
from app.core.config import Settings


def client() -> TestClient:
    return TestClient(create_app(Settings()))


def test_unknown_path_is_a_not_found_envelope_with_the_request_id() -> None:
    response = client().get("/api/v1/nope")

    body = response.json()["error"]
    assert response.status_code == 404
    assert body["code"] == "NOT_FOUND"
    assert body["request_id"] == response.headers["x-request-id"]


def test_wrong_method_is_a_method_not_allowed_envelope() -> None:
    response = client().delete("/api/v1/config")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert "GET" in response.headers["allow"]


def test_invalid_body_lists_the_fields_and_never_echoes_input() -> None:
    response = client().post(
        "/api/v1/auth/request", json={"identifier": "x", "secret": "hunter2"}
    )

    body = response.json()["error"]
    assert response.status_code == 422
    assert body["code"] == "VALIDATION_FAILED"
    assert body["fields"][0]["field"] == "body.identifier"
    assert body["fields"][0]["type"] == "string_too_short"
    assert "hunter2" not in response.text
    assert body["request_id"] == response.headers["x-request-id"]


def test_missing_body_field_is_reported_by_name() -> None:
    response = client().post("/api/v1/auth/request", json={})

    fields = response.json()["error"]["fields"]
    assert [f["field"] for f in fields] == ["body.identifier"]
    assert fields[0]["type"] == "missing"


def test_api_errors_and_rate_limit_carry_the_request_id() -> None:
    http = TestClient(
        create_app(Settings(rate_limit_requests=1, rate_limit_window_seconds=60))
    )

    first = http.get("/api/v1/me")
    limited = http.get("/api/v1/me")

    assert first.json()["error"]["code"] == "AUTH_REQUIRED"
    assert first.json()["error"]["request_id"] == first.headers["x-request-id"]
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "RATE_LIMITED"
    assert limited.json()["error"]["request_id"] == limited.headers["x-request-id"]


def test_unhandled_errors_are_wrapped_without_internals() -> None:
    application: FastAPI = create_app(Settings())

    @application.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("secret internals")

    response = TestClient(application, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in response.text


def test_the_generated_contract_documents_the_envelope_for_422() -> None:
    schema = create_app(Settings()).openapi()

    operation = schema["paths"]["/api/v1/auth/request"]["post"]
    assert operation["responses"]["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert "HTTPValidationError" not in schema["components"]["schemas"]
