"""`GET /api/v1/avatars`: the avatar catalogue endpoint (P1.3)."""

from fastapi.testclient import TestClient

from app.api.deps import get_avatar_service
from app.app import create_app
from app.application.avatars import AvatarService
from app.core.config import Settings
from app.domain.avatars import Avatar


class FakeCatalogue:
    def __init__(self) -> None:
        self.avatars = [
            Avatar(id="avatar-1", image_url="https://x.invalid/1.png", locked=False),
            Avatar(id="avatar-2", image_url="https://x.invalid/2.png", locked=True),
        ]

    async def list_active(self) -> list[Avatar]:
        return list(self.avatars)

    async def get_active(self, avatar_id: str) -> Avatar | None:
        return next((a for a in self.avatars if a.id == avatar_id), None)


def client() -> TestClient:
    app = create_app(
        Settings(database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/x")
    )
    app.dependency_overrides[get_avatar_service] = lambda: AvatarService(
        FakeCatalogue()
    )
    return TestClient(app)


def test_avatars_need_no_sign_in_and_include_locked_ones() -> None:
    response = client().get("/api/v1/avatars")

    assert response.status_code == 200
    assert response.json() == [
        {"id": "avatar-1", "image_url": "https://x.invalid/1.png", "locked": False},
        {"id": "avatar-2", "image_url": "https://x.invalid/2.png", "locked": True},
    ]
