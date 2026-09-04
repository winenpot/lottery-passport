from fastapi.testclient import TestClient

from app.app import create_app
from app.core.config import Settings


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"]


def test_ready_reports_unavailable_database(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "service unavailable"}


def test_cors_allows_configured_origin() -> None:
    with TestClient(create_app(Settings())) as test_client:
        response = test_client.get(
            "/health", headers={"Origin": "http://localhost:3000"}
        )

    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_rate_limit_excludes_health_and_limits_other_routes() -> None:
    settings = Settings(rate_limit_requests=1, rate_limit_window_seconds=60)
    with TestClient(create_app(settings)) as test_client:
        first = test_client.get("/not-found")
        second = test_client.get("/not-found")
        health = test_client.get("/health")

    assert first.status_code == 404
    assert second.status_code == 429
    assert health.status_code == 200
