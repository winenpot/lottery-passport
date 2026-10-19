"""FX1: every error a browser can hit must be CORS-readable.

Without ``expose_headers``, ``Retry-After``/``X-Request-ID`` are invisible to
``fetch()`` even on a handled error. Without the right middleware order, the
rate limiter's 429 and an unhandled 500 skip CORSMiddleware entirely (the
rate limiter answers before reaching it; a bare exception reaches Starlette's
ServerErrorMiddleware, which sits outside every user middleware) and the
browser sees a bare network error instead of a response it can read.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.app import create_app
from app.core.config import Settings

ORIGIN = "http://localhost:5173"


def _settings(**overrides: object) -> Settings:
    return Settings(cors_origins=f'["{ORIGIN}"]', **overrides)  # type: ignore[arg-type]


def test_404_is_readable_across_origins() -> None:
    response = TestClient(create_app(_settings())).get(
        "/api/v1/nope", headers={"Origin": ORIGIN}
    )

    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]
    assert "Retry-After" in response.headers["access-control-expose-headers"]
    assert response.headers["x-request-id"]


def test_rate_limited_429_is_readable_across_origins() -> None:
    client = TestClient(
        create_app(_settings(rate_limit_requests=1, rate_limit_window_seconds=60))
    )
    client.get("/api/v1/me", headers={"Origin": ORIGIN})

    limited = client.get("/api/v1/me", headers={"Origin": ORIGIN})

    assert limited.status_code == 429
    assert limited.headers["access-control-allow-origin"] == ORIGIN
    assert limited.headers["retry-after"]
    assert limited.json()["error"]["code"] == "RATE_LIMITED"


def test_unhandled_500_is_readable_and_carries_a_request_id() -> None:
    application: FastAPI = create_app(_settings())

    @application.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("secret internals")

    response = TestClient(application, raise_server_exceptions=False).get(
        "/boom", headers={"Origin": ORIGIN}
    )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["x-request-id"]
    body = response.json()["error"]
    assert body["code"] == "INTERNAL_ERROR"
    assert body["request_id"] == response.headers["x-request-id"]
    assert "secret" not in response.text


def test_preflight_for_a_paying_write_is_accepted_and_not_rate_limited() -> None:
    client = TestClient(
        create_app(_settings(rate_limit_requests=1, rate_limit_window_seconds=60))
    )

    preflight = client.options(
        "/api/v1/redemptions",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type, idempotency-key, "
            "x-requested-with",
        },
    )
    # A real request right after: if the preflight had consumed the budget
    # of 1, this would be 429 instead of the expected 401 (no session yet).
    real = client.post("/api/v1/redemptions", json={"code": "x"})

    allow_headers = preflight.headers["access-control-allow-headers"].lower()
    assert preflight.status_code == 200
    assert "idempotency-key" in allow_headers
    assert "x-requested-with" in allow_headers
    assert real.status_code != 429
