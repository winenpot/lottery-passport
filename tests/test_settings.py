import pytest

from app.core.config import Settings


def test_settings_use_typed_defaults() -> None:
    settings = Settings()

    assert settings.environment == "development"
    assert settings.db_connect_timeout_seconds == 5
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.allowed_cors_origins == ["http://localhost:3000"]


def test_wildcard_cors_origin_is_supported() -> None:
    settings = Settings(cors_origins="*")

    assert settings.allowed_cors_origins == ["*"]


def test_development_can_use_local_database() -> None:
    settings = Settings(
        environment="development",
        database_url="postgresql+asyncpg://local:local@postgres:5432/lottery_passport",
    )

    assert settings.environment == "development"


def test_postgresql_database_urls_use_async_driver() -> None:
    settings = Settings(
        database_url="postgresql://user:password@db.example/lottery_passport"
    )

    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_demo_rejects_loopback_database() -> None:
    with pytest.raises(ValueError, match="external database"):
        Settings(
            environment="demo",
            database_url="postgresql+asyncpg://local:local@localhost:5432/lottery_passport",
            _env_file=None,
        )


def test_production_accepts_compose_service_database() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql+asyncpg://app:secret@postgres:5432/lottery_passport",
        redemption_code_pepper="p" * 48,
        admin_session_secret="a" * 48,
        _env_file=None,
    )

    assert settings.environment == "production"


def test_production_rejects_a_short_or_blank_pepper() -> None:
    for pepper in ("too-short", "   "):
        with pytest.raises(ValueError, match="REDEMPTION_CODE_PEPPER"):
            Settings(
                environment="production",
                database_url="postgresql+asyncpg://app:secret@postgres:5432/db",
                redemption_code_pepper=pepper,
                _env_file=None,
            )


def test_blank_secrets_are_treated_as_unset() -> None:
    settings = Settings(redemption_code_pepper="", _env_file=None)

    assert settings.redemption_code_pepper is None


def test_unknown_campaign_timezone_is_rejected() -> None:
    with pytest.raises(ValueError, match="time zone"):
        Settings(campaign_timezone="Mars/Olympus", _env_file=None)


_PEPPER = "p" * 40
_EXTERNAL_DB = "postgresql+asyncpg://u:p@db.example/x"


def _deployed(**overrides: object) -> Settings:
    return Settings(
        environment="staging",
        redemption_code_pepper=_PEPPER,
        admin_session_secret="a" * 48,
        database_url=_EXTERNAL_DB,
        _env_file=None,
        **overrides,  # type: ignore[arg-type]
    )


def test_wildcard_cors_is_rejected_outside_development() -> None:
    with pytest.raises(ValueError, match="must not be '\\*'"):
        _deployed(cors_origins="*")


def test_http_cors_origin_is_rejected_outside_development() -> None:
    with pytest.raises(ValueError, match="must use https"):
        _deployed(cors_origins='["http://86.104.82.71:8000"]')


def test_https_and_loopback_cors_origins_are_accepted_outside_development() -> None:
    settings = _deployed(cors_origins='["https://torshx.com","http://localhost:5173"]')

    assert settings.allowed_cors_origins == [
        "https://torshx.com",
        "http://localhost:5173",
    ]


def test_samesite_defaults_to_lax_and_rejects_unknown_values() -> None:
    assert Settings(_env_file=None).session_cookie_samesite == "lax"
    with pytest.raises(ValueError):
        Settings(session_cookie_samesite="bogus", _env_file=None)  # type: ignore[arg-type]


def test_samesite_none_needs_secure_cookies() -> None:
    with pytest.raises(ValueError, match="requires Secure"):
        Settings(session_cookie_samesite="none", _env_file=None)
    assert _deployed(session_cookie_samesite="none").session_cookie_samesite == "none"


def test_host_prefixed_cookie_name_needs_secure_cookies() -> None:
    with pytest.raises(ValueError, match="requires Secure"):
        Settings(session_cookie_name="__Host-lp_session", _env_file=None)
    assert (
        _deployed(session_cookie_name="__Host-lp_session").session_cookie_name
        == "__Host-lp_session"
    )


def test_public_app_origin_is_normalized_and_validated() -> None:
    assert (
        Settings(
            public_app_origin="https://torshx.com/", _env_file=None
        ).public_app_origin
        == "https://torshx.com"
    )
    assert Settings(public_app_origin="", _env_file=None).public_app_origin is None
    with pytest.raises(ValueError, match="scheme \\+ host only"):
        Settings(public_app_origin="https://torshx.com/r", _env_file=None)
    with pytest.raises(ValueError, match="must use https"):
        _deployed(public_app_origin="http://torshx.com")


def test_demo_environment_may_use_http_and_wildcard_origins() -> None:
    settings = Settings(
        environment="demo",
        redemption_code_pepper=_PEPPER,
        database_url=_EXTERNAL_DB,
        cors_origins='["http://86.104.82.71:8000"]',
        _env_file=None,  # type: ignore[call-arg]
    )

    assert settings.allowed_cors_origins == ["http://86.104.82.71:8000"]


def test_staging_and_production_need_an_admin_session_secret() -> None:
    for environment in ("staging", "production"):
        for secret in (None, "short"):
            with pytest.raises(ValueError, match="ADMIN_SESSION_SECRET"):
                Settings(
                    environment=environment,
                    database_url=_EXTERNAL_DB,
                    redemption_code_pepper=_PEPPER,
                    admin_session_secret=secret,
                    cors_origins="https://play.example",
                    _env_file=None,
                )


def test_demo_runs_without_an_admin_session_secret() -> None:
    settings = Settings(
        environment="demo",
        database_url=_EXTERNAL_DB,
        redemption_code_pepper=_PEPPER,
        _env_file=None,
    )

    assert settings.admin_session_secret is None
