import pytest

from app.core.config import Settings


def test_settings_use_typed_defaults() -> None:
    settings = Settings()

    assert settings.environment == "development"
    assert settings.db_connect_timeout_seconds == 5
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_development_can_use_local_database() -> None:
    settings = Settings(
        environment="development",
        database_url="postgresql+asyncpg://local:local@postgres:5432/lottery_passport",
    )

    assert settings.environment == "development"


def test_demo_rejects_local_database() -> None:
    with pytest.raises(ValueError, match="external database"):
        Settings(
            environment="demo",
            database_url="postgresql+asyncpg://local:local@postgres:5432/lottery_passport",
        )
