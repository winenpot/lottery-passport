"""``GET /media/{sha256}.{ext}`` (W10): route wiring only -- the real
storage/validation logic is tested in tests/unit/test_media_service.py
and tests/unit/test_media_domain.py; the admin upload page is covered
end-to-end against real Postgres in tests/integration/test_media_db.py.
"""

from fastapi.testclient import TestClient

from app.api.deps import get_media_service
from app.app import create_app
from app.core.config import Settings
from app.domain.media import MediaContentType, StoredMedia

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
SHA256 = "a" * 64


class FakeMediaService:
    def __init__(self) -> None:
        self.stored: StoredMedia | None = None

    async def get(self, sha256: str) -> StoredMedia | None:
        return self.stored if sha256 == SHA256 else None


def client(service: FakeMediaService) -> TestClient:
    app = create_app(
        Settings(database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/x")
    )
    app.dependency_overrides[get_media_service] = lambda: service
    return TestClient(app)


def test_an_unknown_hash_is_404() -> None:
    response = client(FakeMediaService()).get(f"/media/{SHA256}.png")

    assert response.status_code == 404


def test_a_known_image_is_served_with_a_long_lived_cache_header() -> None:
    service = FakeMediaService()
    service.stored = StoredMedia(content_type=MediaContentType.PNG, data=PNG_BYTES)

    response = client(service).get(f"/media/{SHA256}.png")

    assert response.status_code == 200
    assert response.content == PNG_BYTES
    assert response.headers["content-type"] == "image/png"
    assert "immutable" in response.headers["cache-control"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_the_extension_must_match_the_stored_content_type() -> None:
    """Catches a copy-paste'd wrong extension early, not with a mislabeled
    image served to a browser."""
    service = FakeMediaService()
    service.stored = StoredMedia(content_type=MediaContentType.PNG, data=PNG_BYTES)

    response = client(service).get(f"/media/{SHA256}.jpg")

    assert response.status_code == 404


def test_a_malformed_hash_in_the_url_is_rejected_before_reaching_the_service() -> None:
    response = client(FakeMediaService()).get("/media/not-a-hash.png")

    assert response.status_code == 422
