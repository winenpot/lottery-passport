import random

import pytest
from fastapi.testclient import TestClient

from app.app import create_app
from app.core.config import Settings
from app.infrastructure.sms import ConsoleSmsSender


def random_iranian_phone() -> str:
    # 0912 prefix: never a 0969 test number, which would answer with test_code
    # (a fully random subscriber number hit 0969 once in ~100 runs).
    subscriber = "".join(str(random.randint(0, 9)) for _ in range(7))
    return f"+98912{subscriber}"


@pytest.mark.asyncio
async def test_passwordless_authentication_api(test_database_url: str) -> None:
    settings = Settings(
        database_url=test_database_url,
        cors_origins="*",
        _env_file=None,
    )
    application = create_app(settings)
    identifier = random_iranian_phone()

    with TestClient(application, headers={"X-Requested-With": "test"}) as client:
        request_response = client.post(
            "/api/v1/auth/request", json={"identifier": identifier}
        )
        sender = application.state.sms_sender
        assert isinstance(sender, ConsoleSmsSender)
        assert request_response.status_code == 202
        assert request_response.json() == {
            "resend_after_seconds": 60,
            "expires_in_seconds": 150,
            "code_length": 6,
        }
        assert sender.last_code is not None
        assert sender.last_purpose == "signup"

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

        # display_name has no charset restriction of its own, unlike nickname
        # (which the nickname rules would reject outright); the reserved-name
        # check is what stops "Lich King" here.
        reserved_response = client.patch(
            "/api/v1/me", json={"display_name": "Lich King"}
        )
        assert reserved_response.status_code == 422
        assert reserved_response.json()["error"]["code"] == "DISPLAY_NAME_RESERVED"
        assert client.get("/api/v1/me").json()["display_name"] == "Phase Two"

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


@pytest.mark.asyncio
async def test_a_non_iranian_number_is_rejected(test_database_url: str) -> None:
    settings = Settings(
        database_url=test_database_url, cors_origins="*", _env_file=None
    )
    application = create_app(settings)

    with TestClient(application) as client:
        response = client.post(
            "/api/v1/auth/request", json={"identifier": "+1 212 555 0100"}
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PHONE_INVALID"


@pytest.mark.asyncio
async def test_an_unusual_prefix_is_rejected_without_an_sms_attempt(
    test_database_url: str,
) -> None:
    settings = Settings(
        database_url=test_database_url, cors_origins="*", _env_file=None
    )
    application = create_app(settings)
    # 940 is shape-valid (9 + 9 digits) but not on any known allocated range.
    identifier = "+989401234567"

    with TestClient(application) as client:
        response = client.post("/api/v1/auth/request", json={"identifier": identifier})
        sender = application.state.sms_sender
        assert isinstance(sender, ConsoleSmsSender)
        assert sender.last_code is None, "an unusual number must never reach the sender"

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PHONE_UNUSUAL"


@pytest.mark.asyncio
async def test_resending_too_soon_is_rejected(test_database_url: str) -> None:
    settings = Settings(
        database_url=test_database_url, cors_origins="*", _env_file=None
    )
    application = create_app(settings)
    identifier = random_iranian_phone()

    with TestClient(application) as client:
        first = client.post("/api/v1/auth/request", json={"identifier": identifier})
        second = client.post("/api/v1/auth/request", json={"identifier": identifier})

    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "OTP_COOLDOWN"
    assert "Retry-After" in second.headers


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
