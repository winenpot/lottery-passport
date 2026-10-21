"""``GET /me/achievements`` and ``GET /achievements`` (B44/W13): route wiring.

``AchievementService``/``ChallengeService`` claim-time unlock+pay logic is
exercised against fakes in tests/unit/test_challenge_service.py and
against real Postgres in tests/integration/test_challenges_db.py; this
file only proves the routes serialize what the service returns.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.deps import get_achievement_service, get_current_user
from app.app import create_app
from app.core.config import Settings
from app.domain.achievements import (
    AchievementFact,
    AchievementProgress,
    UnlockedAchievement,
)
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
        self.progress: list[AchievementProgress] = []

    async def list_unlocked(self, user_id: UUID) -> list[UnlockedAchievement]:
        return self.unlocked

    async def list_progress(self, user_id: UUID) -> list[AchievementProgress]:
        return self.progress


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


def test_progress_lists_every_active_row_locked_or_not() -> None:
    """B44/W13: unlike ``/me/achievements``, a never-unlocked row still
    appears, locked, with its progress -- a new player sees 0/3, 0/7, 0/30."""
    service = FakeAchievementService()
    service.progress = [
        AchievementProgress(
            id="streak_3",
            fact=AchievementFact.CHECKIN_STREAK,
            threshold=3,
            reward_coins=20,
            have=0,
            unlocked=False,
            unlocked_at=None,
        ),
        AchievementProgress(
            id="streak_7",
            fact=AchievementFact.CHECKIN_STREAK,
            threshold=7,
            reward_coins=50,
            have=7,
            unlocked=True,
            unlocked_at=NOW,
        ),
    ]

    response = client(service).get("/api/v1/achievements")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    locked, unlocked = body
    assert (
        locked["id"],
        locked["have"],
        locked["unlocked"],
        locked["unlocked_at"],
    ) == (
        "streak_3",
        0,
        False,
        None,
    )
    assert (unlocked["id"], unlocked["have"], unlocked["unlocked"]) == (
        "streak_7",
        7,
        True,
    )
    assert datetime.fromisoformat(unlocked["unlocked_at"]) == NOW


def test_achievements_route_also_requires_sign_in() -> None:
    app = create_app(
        Settings(database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/x")
    )
    app.dependency_overrides[get_achievement_service] = lambda: FakeAchievementService()

    response = TestClient(app).get("/api/v1/achievements")

    assert response.status_code == 401
