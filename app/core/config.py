import json
from functools import lru_cache
from typing import Self
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Lottery Passport API"
    environment: str = "development"
    port: int = Field(default=8000, ge=1, le=65535)
    forwarded_allow_ips: str = "127.0.0.1"
    api_key: SecretStr | None = None
    email_provider: str = "development"
    auth_challenge_ttl_seconds: int = Field(default=600, ge=60, le=3_600)
    auth_session_ttl_seconds: int = Field(default=2_592_000, ge=300, le=31_536_000)
    auth_max_verification_attempts: int = Field(default=5, ge=1, le=20)
    session_cookie_name: str = "lottery_passport_session"
    log_level: str = "INFO"
    log_json: bool = True
    rate_limit_requests: int = Field(default=60, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3_600)
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/lottery_passport"
    )
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    cors_origins: str = '["http://localhost:3000"]'

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_async_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @model_validator(mode="after")
    def reject_local_database_outside_development(self) -> Self:
        deployment_environments = {"demo", "staging", "production"}
        database_host = urlparse(self.database_url).hostname
        local_hosts = {"localhost", "127.0.0.1", "::1", "postgres"}
        if (
            self.environment.lower() in deployment_environments
            and database_host in local_hosts
        ):
            raise ValueError(
                "DATABASE_URL must reference an external database outside development"
            )
        if self.environment.lower() in deployment_environments and self.api_key is None:
            raise ValueError("API_KEY must be configured outside development")
        return self

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
    def secure_session_cookies(self) -> bool:
        return self.environment.lower() != "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
