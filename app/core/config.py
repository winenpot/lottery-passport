import json
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.phone import PhoneNumberError, normalize_iranian_mobile


class Settings(BaseSettings):
    app_name: str = "Lottery Passport API"
    environment: str = "development"
    # The deployed commit, shown by GET /health. Baked into the image at build
    # time (Dockerfile ARG GIT_COMMIT, set by CI). None when unknown.
    git_commit: str | None = None
    port: int = Field(default=8000, ge=1, le=65535)
    forwarded_allow_ips: str = "127.0.0.1"
    redemption_code_pepper: SecretStr | None = None
    redemption_daily_limit_per_user: int = Field(default=20, ge=1, le=1_000)
    redemption_max_invalid_attempts_per_hour: int = Field(default=10, ge=1, le=1_000)
    # Welcome bonus on a user's first successfully redeemed code (ADR 0010);
    # a `reward_rules` row for key "first_code" overrides or disables it.
    first_code_bonus_coins: int = Field(default=50, ge=0, le=100_000)
    # Flavor team switch lock (app/domain/teams.py, P1): days after each join
    # or switch before the player may change team again.
    team_lock_days: int = Field(default=30, ge=1, le=365)
    # Mini-games (app/domain/mini_games.py, G1): this many REJECTED
    # (implausible) runs for one player in one Tehran day writes an
    # audit_log flag for admin review. Not an auto-ban.
    mini_game_rejected_review_threshold: int = Field(default=3, ge=1, le=100)
    campaign_timezone: str = "Asia/Tehran"
    # Current terms of service; players accept it by sending this exact value.
    terms_version: str = "2026-10-01"
    # false: sign-up and scanning do not need accepted terms (staging/demo, until
    # the legal text exists). Production refuses false (validator below).
    terms_required: bool = True
    kavenegar_otp_api_key: SecretStr | None = None
    # Signs the admin panel's session cookie. Unset: a random key per process
    # (admin sessions end on restart); required in staging/production.
    admin_session_secret: SecretStr | None = None
    admin_session_max_age_seconds: int = Field(default=3600, ge=300, le=8 * 3600)
    kavenegar_template_login: str = "login"
    kavenegar_template_signup: str = "signup"
    otp_ttl_seconds: int = Field(default=150, ge=30, le=600)
    otp_max_attempts: int = Field(default=5, ge=1, le=20)
    otp_resend_seconds: int = Field(default=60, ge=10, le=600)
    otp_daily_limit_per_phone: int = Field(default=5, ge=1, le=50)
    # 0969 test numbers (code in the response, no SMS). Unset: on in
    # development/demo only. true is allowed on staging; production refuses it.
    # TODO: remove this on production (app/application/otp_test_numbers.py).
    otp_test_numbers: bool | None = None
    # Comma-separated mobile numbers that may receive a real SMS (staging, so a
    # public test server is not an SMS relay). Empty: anyone. Production refuses
    # a non-empty list.
    otp_allowed_phones: str = ""
    auth_session_ttl_seconds: int = Field(default=2_592_000, ge=300, le=31_536_000)
    session_cookie_name: str = "lottery_passport_session"
    log_level: str = "INFO"
    log_json: bool = True
    rate_limit_requests: int = Field(default=60, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3_600)
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/lottery_passport"
    )
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    # Applied to every API/worker connection; migrations use their own engine.
    db_statement_timeout_ms: int = Field(default=15_000, ge=100, le=600_000)
    cors_origins: str = '["http://localhost:3000"]'
    # "none" is for a cross-site frontend (Chrome only; Safari/Firefox block it).
    # Prefer a same-origin proxy and keep "lax" (docs/API_CONTRACT.md, hosting rules).
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    # Public origin of the app (scheme + host, no path); builds the QR URLs.
    # Printed QR codes freeze it, so it is never hard-coded.
    public_app_origin: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_async_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator(
        "redemption_code_pepper",
        "kavenegar_otp_api_key",
        "admin_session_secret",
        mode="before",
    )
    @classmethod
    def treat_blank_secrets_as_unset(cls, value: object) -> object:
        # ".env.example" ships "REDEMPTION_CODE_PEPPER=" (empty). An empty
        # HMAC key must never count as configured.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("public_app_origin", mode="before")
    @classmethod
    def normalize_public_app_origin(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str):
            return value
        origin = value.strip().rstrip("/")
        parsed = urlparse(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "PUBLIC_APP_ORIGIN must be scheme + host only, e.g. https://torshx.com"
            )
        return origin

    @field_validator("campaign_timezone")
    @classmethod
    def require_known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown IANA time zone: {value}") from error
        return value

    @model_validator(mode="after")
    def reject_local_database_outside_development(self) -> Self:
        deployment_environments = {"demo", "staging", "production"}
        database_host = urlparse(self.database_url).hostname
        # Loopback only. A Compose service name such as "postgres" is the
        # normal production setup on a single VM (docs/OPERATIONS.md).
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if (
            self.environment.lower() in deployment_environments
            and database_host in local_hosts
        ):
            raise ValueError(
                "DATABASE_URL must reference an external database outside development"
            )
        if self.environment.lower() in deployment_environments and (
            self.redemption_code_pepper is None
            or len(self.redemption_code_pepper.get_secret_value()) < 32
        ):
            raise ValueError(
                "REDEMPTION_CODE_PEPPER must be at least 32 characters outside "
                "development (generate with: python -c "
                '"import secrets; print(secrets.token_urlsafe(48))")'
            )
        if self.session_cookie_samesite == "none" and not self.secure_session_cookies:
            raise ValueError("SESSION_COOKIE_SAMESITE=none requires Secure cookies")
        if self.environment.lower() == "production" and not self.terms_required:
            raise ValueError("TERMS_REQUIRED=false is not allowed in production")
        allowed_phones = self.allowed_otp_phones  # raises on a malformed number
        if self.environment.lower() == "production" and (
            self.test_numbers_enabled or allowed_phones
        ):
            raise ValueError(
                "OTP_TEST_NUMBERS and OTP_ALLOWED_PHONES are not allowed in production"
            )
        # demo is the throwaway test deployment (test API, test DB, test
        # frontend, possibly plain http): only staging/production are strict.
        if self.environment.lower() in {"staging", "production"}:
            self._require_safe_origins()
            if (
                self.admin_session_secret is None
                or len(self.admin_session_secret.get_secret_value()) < 32
            ):
                raise ValueError(
                    "ADMIN_SESSION_SECRET must be at least 32 characters in "
                    "staging/production"
                )
        return self

    def _require_safe_origins(self) -> None:
        """Outside development: no wildcard, and https (loopback http is fine)."""
        origins = self.allowed_cors_origins
        if "*" in origins:
            raise ValueError("CORS_ORIGINS must not be '*' outside development")
        for origin in [
            *origins,
            *([self.public_app_origin] if self.public_app_origin else []),
        ]:
            parsed = urlparse(origin)
            loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
                raise ValueError(
                    f"origin {origin!r} must use https outside development "
                    "(CORS_ORIGINS / PUBLIC_APP_ORIGIN)"
                )

    @property
    def allowed_cors_origins(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        try:
            parsed = json.loads(self.cors_origins)
        except json.JSONDecodeError:
            return [origin.strip() for origin in self.cors_origins.split(",")]
        if not isinstance(parsed, list) or not all(
            isinstance(origin, str) for origin in parsed
        ):
            raise ValueError("CORS_ORIGINS must be '*' or a JSON array of strings")
        return parsed

    @property
    def campaign_zone(self) -> ZoneInfo:
        return ZoneInfo(self.campaign_timezone)

    @property
    def test_numbers_enabled(self) -> bool:
        if self.otp_test_numbers is not None:
            return self.otp_test_numbers
        return self.environment.lower() in {"development", "demo"}

    @property
    def allowed_otp_phones(self) -> frozenset[str]:
        numbers = set()
        for raw in self.otp_allowed_phones.replace(";", ",").split(","):
            if not raw.strip():
                continue
            try:
                numbers.add(normalize_iranian_mobile(raw))
            except PhoneNumberError as error:
                # The message never repeats the value (it is a phone number).
                raise ValueError("OTP_ALLOWED_PHONES has an invalid number") from error
        return frozenset(numbers)

    @property
    def secure_session_cookies(self) -> bool:
        return self.environment.lower() != "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
