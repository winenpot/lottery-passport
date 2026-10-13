"""CSRF guard: cookie writes need X-Requested-With and an allowed Origin."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.api.middleware import CsrfMiddleware

COOKIE = "lottery_passport_session"
FRONTEND = "http://86.104.82.71:8000"


def client(origins: list[str] | None = None) -> TestClient:
    allowed = origins or [FRONTEND]
    app = FastAPI()

    @app.post("/write")
    async def write() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/read")
    async def read() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(CsrfMiddleware, cookie_name=COOKIE, allowed_origins=allowed)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return TestClient(app)


def test_a_cookie_write_without_the_header_is_rejected() -> None:
    http = client()
    http.cookies.set(COOKIE, "token")

    response = http.post("/write")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REJECTED"


def test_a_cookie_write_with_the_header_from_an_allowed_origin_passes() -> None:
    http = client()
    http.cookies.set(COOKIE, "token")

    response = http.post(
        "/write", headers={"X-Requested-With": "torshx", "Origin": FRONTEND}
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND


def test_a_foreign_origin_is_rejected_even_with_the_header() -> None:
    http = client()
    http.cookies.set(COOKIE, "token")

    response = http.post(
        "/write",
        headers={"X-Requested-With": "x", "Origin": "https://evil.example"},
    )

    assert response.status_code == 403


def test_reads_and_cookieless_writes_are_not_affected() -> None:
    http = client()

    assert http.post("/write").status_code == 200  # sign-in has no session yet
    http.cookies.set(COOKIE, "token")
    assert http.get("/read").status_code == 200


def test_a_rejection_still_carries_cors_headers_so_the_frontend_can_read_it() -> None:
    http = client()
    http.cookies.set(COOKIE, "token")

    response = http.post("/write", headers={"Origin": FRONTEND})

    assert response.status_code == 403
    assert response.headers["access-control-allow-origin"] == FRONTEND
