"""FX3 (terms/privacy links) and FX7 (``/config.features`` read side)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_app_config_service
from app.app import create_app
from app.application.app_config import AppConfigService, FeatureFlags
from app.core.config import Settings
from app.domain.venues import Venue

TEHRAN = ZoneInfo("Asia/Tehran")
NOW = datetime(2026, 10, 10, 8, 30, tzinfo=UTC)


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeVenues:
    async def list_active(self) -> list[Venue]:
        return []

    async def exists_active(self, venue_id: str) -> bool:
        return False


def _client(**app_config_kwargs: object) -> TestClient:
    service = AppConfigService(
        FakeClock(),
        TEHRAN,
        "2026-10-01",
        20,
        FakeVenues(),
        terms_required=bool(app_config_kwargs.get("terms_required", True)),
        terms_url=app_config_kwargs.get("terms_url"),  # type: ignore[arg-type]
        privacy_url=app_config_kwargs.get("privacy_url"),  # type: ignore[arg-type]
        features=app_config_kwargs.get("features"),  # type: ignore[arg-type]
    )
    app = create_app(Settings())
    app.dependency_overrides[get_app_config_service] = lambda: service
    return TestClient(app)


def test_terms_and_privacy_url_are_null_by_default() -> None:
    response = _client().get("/api/v1/config")

    body = response.json()
    assert body["terms_url"] is None
    assert body["privacy_url"] is None


def test_terms_and_privacy_url_pass_through_when_set() -> None:
    response = _client(
        terms_url="https://torshx.com/terms",
        privacy_url="https://torshx.com/privacy",
    ).get("/api/v1/config")

    body = response.json()
    assert body["terms_url"] == "https://torshx.com/terms"
    assert body["privacy_url"] == "https://torshx.com/privacy"


def test_terms_url_must_be_https_outside_development() -> None:
    with pytest.raises(ValueError, match="TERMS_URL must use https"):
        Settings(
            environment="staging",
            terms_url="http://torshx.com/terms",
            database_url="postgresql+asyncpg://u:p@db.example.com/lp",
            redemption_code_pepper="x" * 32,
            admin_session_secret="y" * 32,
            cors_origins='["https://staging.torshx.com"]',
        )


def test_features_default_matches_what_has_actually_shipped() -> None:
    response = _client().get("/api/v1/config")

    assert response.json()["features"] == {
        "mini_games": True,
        "leaderboard": False,
        "venue_checkin": False,
        "diamonds": False,
    }


def test_features_are_overridable_without_a_deploy() -> None:
    response = _client(features=FeatureFlags(mini_games=False, leaderboard=True)).get(
        "/api/v1/config"
    )

    body = response.json()["features"]
    assert body["mini_games"] is False
    assert body["leaderboard"] is True


def test_settings_feature_flags_build_the_service_defaults() -> None:
    settings = Settings(feature_mini_games=False, feature_leaderboard=True)

    assert settings.feature_mini_games is False
    assert settings.feature_leaderboard is True
