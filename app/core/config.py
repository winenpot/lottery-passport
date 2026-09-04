from functools import lru_cache
from typing import Self
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Lottery Passport API"
    environment: str = "development"
    port: int = Field(default=8000, ge=1, le=65535)
    forwarded_allow_ips: str = "127.0.0.1"
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/lottery_passport"
    )
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
