"""POST /redemptions needs accepted terms and a nickname."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_redemption_service
from app.app import create_app
from app.application.redemption_codes import RedemptionResult
from app.core.config import Settings
from app.domain.passports import CityCode
from app.domain.users import AccountStatus, User, UserRole, VerificationStatus

NOW = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)


def make_user(*, nickname: str | None, terms: bool) -> User:
    return User(
        id=uuid4(),
        identifier="+989123456789",
        display_name=None,
        account_status=AccountStatus.ACTIVE,
        verification_status=VerificationStatus.VERIFIED,
        role=UserRole.PLAYER,
        created_at=NOW,
        updated_at=NOW,
        nickname=nickname,
        terms_version="2026-10-01" if terms else None,
        terms_accepted_at=NOW if terms else None,
    )


class FakeRedemptions:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str]] = []

    async def redeem(self, user_id: UUID, code: str) -> RedemptionResult:
        self.calls.append((user_id, code))
        return RedemptionResult(
            city=CityCode.TOKYO,
            entries_added=1,
            city_entries=1,
            coins_awarded=10,
            coin_balance=10,
            replayed=False,
        )


def scan(user: User) -> tuple[int, str | None, FakeRedemptions]:
    fake = FakeRedemptions()
    application = create_app(Settings())
    application.dependency_overrides[get_current_user] = lambda: user
    application.dependency_overrides[get_redemption_service] = lambda: fake
    response = TestClient(application).post("/api/v1/redemptions", json={"code": "x"})
    return response.status_code, response.json().get("error", {}).get("code"), fake


def test_terms_not_accepted_is_refused_first() -> None:
    status, code, fake = scan(make_user(nickname=None, terms=False))

    assert (status, code) == (403, "TERMS_NOT_ACCEPTED")
    assert fake.calls == []


def test_a_missing_nickname_is_refused() -> None:
    status, code, fake = scan(make_user(nickname=None, terms=True))

    assert (status, code) == (403, "PROFILE_INCOMPLETE")
    assert fake.calls == []


def test_terms_without_nickname_checks_terms_only_when_missing() -> None:
    status, code, _ = scan(make_user(nickname="NightOwl", terms=False))

    assert (status, code) == (403, "TERMS_NOT_ACCEPTED")


def test_a_complete_profile_reaches_the_service() -> None:
    user = make_user(nickname="NightOwl", terms=True)

    status, code, fake = scan(user)

    assert (status, code) == (200, None)
    assert fake.calls == [(user.id, "x")]
