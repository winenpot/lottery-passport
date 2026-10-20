"""``PATCH /me`` ``referrer_code`` binding and ``GET /me/referrals``: route
wiring and error mapping only. ``ReferralService`` itself is exercised
against fakes in nothing yet (pure parts in test_referrals_domain.py) and
against real Postgres in tests/integration/test_referrals_db.py.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_me_service, get_referral_service
from app.app import create_app
from app.application.me import MeExtras
from app.application.referrals import (
    ReferralBindError,
    ReferralBindRefusal,
    ReferralStatus,
)
from app.core.config import Settings
from app.domain.users import AccountStatus, User, UserRole, VerificationStatus

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
USER_ID = UUID(int=1)


def make_user() -> User:
    return User(
        id=USER_ID,
        identifier="+989****0001",
        display_name=None,
        account_status=AccountStatus.ACTIVE,
        verification_status=VerificationStatus.VERIFIED,
        role=UserRole.PLAYER,
        created_at=NOW,
        updated_at=NOW,
        nickname="NightOwl",
        terms_version="2026-10-01",
        terms_accepted_at=NOW,
    )


class FakeMeService:
    async def extras(self, user_id: UUID) -> MeExtras:
        return MeExtras(team=None, last_scanned_flavor=None)


class FakeReferralService:
    def __init__(self) -> None:
        self.bind_calls: list[tuple[UUID, str]] = []
        self.bind_error: ReferralBindError | None = None
        self.status_result = ReferralStatus(
            referral_code="ABCD1234",
            invited_count=0,
            qualified_count=0,
            pending_count=0,
            coins_earned=0,
        )

    async def settle(self, user_id: UUID) -> None:
        return None

    async def ensure_code(self, user_id: UUID) -> str:
        return self.status_result.referral_code

    async def bind(self, invitee_id: UUID, referral_code: str) -> None:
        self.bind_calls.append((invitee_id, referral_code))
        if self.bind_error is not None:
            raise self.bind_error

    async def status(self, user_id: UUID) -> ReferralStatus:
        return self.status_result


def client(service: FakeReferralService) -> TestClient:
    app = create_app(
        Settings(database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/x")
    )
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_me_service] = lambda: FakeMeService()
    app.dependency_overrides[get_referral_service] = lambda: service
    return TestClient(app, headers={"X-Requested-With": "test"})


def test_get_me_includes_the_referral_code() -> None:
    service = FakeReferralService()

    response = client(service).get("/api/v1/me")

    assert response.status_code == 200
    assert response.json()["referral_code"] == "ABCD1234"


def test_patch_me_binds_a_referrer_code() -> None:
    service = FakeReferralService()

    response = client(service).patch("/api/v1/me", json={"referrer_code": "FRIEND01"})

    assert response.status_code == 200
    assert service.bind_calls == [(USER_ID, "FRIEND01")]


def test_patch_me_without_referrer_code_never_calls_bind() -> None:
    service = FakeReferralService()

    response = client(service).patch("/api/v1/me", json={})

    assert response.status_code == 200
    assert service.bind_calls == []


def test_an_unknown_referral_code_is_422() -> None:
    service = FakeReferralService()
    service.bind_error = ReferralBindError(ReferralBindRefusal.CODE_UNKNOWN)

    response = client(service).patch("/api/v1/me", json={"referrer_code": "NOPE0000"})

    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "REFERRAL_CODE_UNKNOWN",
    )


def test_self_referral_is_422() -> None:
    service = FakeReferralService()
    service.bind_error = ReferralBindError(ReferralBindRefusal.SELF)

    response = client(service).patch("/api/v1/me", json={"referrer_code": "OWNCODE1"})

    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "REFERRAL_SELF",
    )


def test_a_second_bind_attempt_is_409() -> None:
    service = FakeReferralService()
    service.bind_error = ReferralBindError(ReferralBindRefusal.ALREADY_BOUND)

    response = client(service).patch("/api/v1/me", json={"referrer_code": "OTHER001"})

    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "REFERRAL_ALREADY_BOUND",
    )


def test_binding_after_a_code_was_redeemed_is_422() -> None:
    service = FakeReferralService()
    service.bind_error = ReferralBindError(ReferralBindRefusal.TOO_LATE)

    response = client(service).patch("/api/v1/me", json={"referrer_code": "LATE0001"})

    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "REFERRAL_CODE_TOO_LATE",
    )


def test_get_my_referrals_reports_the_status() -> None:
    service = FakeReferralService()
    service.status_result = ReferralStatus(
        referral_code="ABCD1234",
        invited_count=3,
        qualified_count=1,
        pending_count=2,
        coins_earned=20,
    )

    response = client(service).get("/api/v1/me/referrals")

    assert response.status_code == 200
    assert response.json() == {
        "referral_code": "ABCD1234",
        "invited_count": 3,
        "qualified_count": 1,
        "pending_count": 2,
        "coins_earned": 20,
    }
