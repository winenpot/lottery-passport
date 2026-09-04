from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_unavailable_database(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "service unavailable"}
