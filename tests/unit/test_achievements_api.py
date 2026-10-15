"""``GET /me/achievements`` (AC1 MVP slice): route wiring.

``AchievementService``/``ChallengeService`` claim-time unlock+pay logic is
exercised against fakes in tests/unit/test_challenge_service.py and
against real Postgres in tests/integration/test_challenges_db.py; this
file only proves the route serializes what the service returns.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.deps import get_achievement_service, get_current_user
from app.app import create_app
from app.core.config import Settings
from app.domain.achievements import UnlockedAchievement
from app.domain.users import AccountStatus, User, UserRole, VerificationStatus

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
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
    )


class FakeAchievementService:
    def __init__(self) -> None:
        self.unlocked: list[UnlockedAchievement] = []

    async def list_unlocked(self, user_id: UUID) -> list[UnlockedAchievement]:
        return self.unlocked


def client(service: FakeAchievementService) -> TestClient:
    app = create_app(
        Settings(database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/x")
    )
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_achievement_service] = lambda: service
    return TestClient(app)


def test_no_achievements_unlocked_yet_is_an_empty_list() -> None:
    response = client(FakeAchievementService()).get("/api/v1/me/achievements")

    assert (response.status_code, response.json()) == (200, [])


def test_unlocked_achievements_are_serialized() -> None:
    service = FakeAchievementService()
    service.unlocked = [
        UnlockedAchievement(
            id="streak_7", threshold=7, reward_coins=50, unlocked_at=NOW
        )
    ]

    response = client(service).get("/api/v1/me/achievements")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert (body[0]["id"], body[0]["threshold"], body[0]["reward_coins"]) == (
        "streak_7",
        7,
        50,
    )
    assert datetime.fromisoformat(body[0]["unlocked_at"]) == NOW


def test_signed_out_is_401() -> None:
    app = create_app(
        Settings(database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/x")
    )
    app.dependency_overrides[get_achievement_service] = lambda: FakeAchievementService()

    response = TestClient(app).get("/api/v1/me/achievements")

    assert response.status_code == 401
