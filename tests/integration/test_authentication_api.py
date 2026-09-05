from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.app import create_app
from app.core.config import Settings
from app.infrastructure.email import DevelopmentEmailSender


@pytest.mark.asyncio
async def test_passwordless_authentication_api(test_database_url: str) -> None:
    settings = Settings(
        database_url=test_database_url,
        email_provider="development",
        cors_origins="*",
        _env_file=None,
    )
    application = create_app(settings)
    identifier = f"phase2-{uuid4().hex}@example.com"

    with TestClient(application) as client:
        request_response = client.post(
            "/api/v1/auth/request", json={"identifier": identifier}
        )
        sender = application.state.email_sender
        assert isinstance(sender, DevelopmentEmailSender)
        assert request_response.status_code == 202
        assert sender.last_code is not None

        verify_response = client.post(
            "/api/v1/auth/verify",
            json={"identifier": identifier, "code": sender.last_code},
        )
        assert verify_response.status_code == 200
        assert verify_response.json()["identifier"] == identifier

        me_response = client.get("/api/v1/me")
        assert me_response.status_code == 200

        update_response = client.patch("/api/v1/me", json={"display_name": "Phase Two"})
        assert update_response.status_code == 200
        assert update_response.json()["display_name"] == "Phase Two"

        logout_response = client.post("/api/v1/auth/logout")
        assert logout_response.status_code == 204
        assert client.get("/api/v1/me").status_code == 401


@pytest.mark.asyncio
async def test_me_requires_session(test_database_url: str) -> None:
    settings = Settings(database_url=test_database_url, _env_file=None)
    application = create_app(settings)

    with TestClient(application) as client:
        response = client.get("/api/v1/me")

    assert response.status_code == 401


def test_openapi_describes_session_cookie_security() -> None:
    settings = Settings(_env_file=None)
    application = create_app(settings)
    schema = application.openapi()

    assert schema["components"]["securitySchemes"]["Session Cookie"] == {
        "type": "apiKey",
        "in": "cookie",
        "name": "lottery_passport_session",
    }
    assert schema["paths"]["/api/v1/me"]["get"]["security"] == [{"Session Cookie": []}]
