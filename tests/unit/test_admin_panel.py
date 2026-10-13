"""The /admin panel over HTTP: cookie, redirects, CSRF and rate-limit rules.

The panel's data views need PostgreSQL; these tests stop at the sign-in
pages, which do not touch the database.
"""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.app import create_app
from app.application.authentication import (
    AuthenticationError,
    RequestChallengeResult,
)
from app.core.config import Settings
from app.domain.users import User
from app.infrastructure.admin import PhoneSignInBackend

ADMIN_ID = uuid4()


class FakeAdminAuth:
    """Stands in for AuthenticationService's three admin methods."""

    def __init__(self) -> None:
        self.admin_active = True
        self.requested: list[str] = []

    async def request_admin_challenge(self, identifier: str) -> RequestChallengeResult:
        self.requested.append(identifier)
        return RequestChallengeResult(60, 150, 6, test_code="123456")

    async def verify_admin_challenge(self, identifier: str, code: str) -> User:
        if code != "123456":
            raise AuthenticationError("invalid authentication challenge")
        return _admin()

    async def get_active_admin(self, user_id: UUID) -> User | None:
        return _admin() if self.admin_active and user_id == ADMIN_ID else None


def _admin() -> User:
    from datetime import UTC, datetime

    from app.domain.users import AccountStatus, UserRole, VerificationStatus

    now = datetime(2026, 10, 13, tzinfo=UTC)
    return User(
        id=ADMIN_ID,
        identifier="+989121112233",
        display_name=None,
        account_status=AccountStatus.ACTIVE,
        verification_status=VerificationStatus.VERIFIED,
        role=UserRole.ADMIN,
        created_at=now,
        updated_at=now,
    )


def panel(environment: str = "development") -> tuple[TestClient, FakeAdminAuth]:
    application = create_app(Settings(environment=environment, _env_file=None))  # type: ignore[call-arg]
    fake = FakeAdminAuth()
    backend = application.state.admin.authentication_backend
    assert isinstance(backend, PhoneSignInBackend)
    backend.service = fake  # type: ignore[assignment]
    return TestClient(application, follow_redirects=False), fake


def sign_in(client: TestClient) -> None:
    sent = client.post("/admin/login", data={"action": "send", "phone": "09121112233"})
    assert sent.status_code == 303
    done = client.post("/admin/login", data={"action": "verify", "code": "123456"})
    assert done.status_code == 302


def test_the_panel_redirects_to_sign_in_without_a_session() -> None:
    client, _ = panel()

    response = client.get("/admin/")

    assert response.status_code in {302, 303, 307}
    assert "/admin/login" in response.headers["location"]


def test_the_sign_in_page_asks_for_a_phone_number_not_a_password() -> None:
    client, _ = panel()

    page = client.get("/admin/login").text

    assert 'name="phone"' in page
    assert 'type="password"' not in page


def test_sending_a_code_moves_to_the_code_step_and_sets_a_strict_admin_cookie() -> None:
    client, fake = panel()

    response = client.post(
        "/admin/login", data={"action": "send", "phone": "09121112233"}
    )

    assert response.status_code == 303
    assert "step=code" in response.headers["location"]
    assert fake.requested == ["09121112233"]
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith("lottery_passport_admin=")
    assert "path=/admin" in cookie
    assert "samesite=strict" in cookie
    assert "httponly" in cookie


def test_the_demo_shows_the_test_code_on_the_code_step() -> None:
    client, _ = panel("development")
    client.post("/admin/login", data={"action": "send", "phone": "09690000001"})

    page = client.get("/admin/login?step=code&m=sent").text

    assert "123456" in page


def test_a_wrong_code_stays_on_the_code_step() -> None:
    client, _ = panel()
    client.post("/admin/login", data={"action": "send", "phone": "09121112233"})

    response = client.post("/admin/login", data={"action": "verify", "code": "999999"})

    assert response.status_code == 303
    assert "m=bad" in response.headers["location"]


def test_an_admin_gets_in_and_a_demotion_locks_them_out_on_the_next_request() -> None:
    client, fake = panel()
    sign_in(client)

    assert client.get("/admin/").status_code == 200

    fake.admin_active = False
    response = client.get("/admin/")
    assert response.status_code in {302, 303, 307}
    assert "/admin/login" in response.headers["location"]


def test_a_cross_site_post_to_the_panel_is_rejected() -> None:
    client, fake = panel()

    response = client.post(
        "/admin/login",
        data={"action": "send", "phone": "09121112233"},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REJECTED"
    assert fake.requested == []


def test_panel_forms_work_with_a_player_cookie_and_no_csrf_header() -> None:
    client, _ = panel()
    client.cookies.set("lottery_passport_session", "player-token")

    response = client.post(
        "/admin/login",
        data={"action": "send", "phone": "09121112233"},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 303


def test_player_api_writes_still_need_the_csrf_header() -> None:
    client, _ = panel()
    client.cookies.set("lottery_passport_session", "player-token")

    response = client.patch("/api/v1/me", json={})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REJECTED"
