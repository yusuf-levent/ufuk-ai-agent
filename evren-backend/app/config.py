from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _parse_comma_separated(value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    upstream_base_url: str = "https://evren-llmapi.ssyz.org.tr/v1"
    upstream_api_key: SecretStr
    upstream_auth_header: Literal["Authorization", "X-API-Key"] = "Authorization"
    upstream_timeout_seconds: float = Field(default=300.0, gt=0)

    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = Field(default=900, gt=0)

    database_url: str = "postgresql+asyncpg://evren:evren@localhost:5433/evren"
    redis_url: str = "redis://localhost:6380/0"

    allowed_origins: Annotated[list[str], NoDecode] = []
    admin_emails: Annotated[list[str], NoDecode] = []
    environment: Literal["dev", "prod"] = "dev"
    request_max_body_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    @field_validator("allowed_origins", "admin_emails", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: str | list[str]) -> list[str]:
        return _parse_comma_separated(value)

    @field_validator("upstream_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("jwt_secret")
    @classmethod
    def _require_long_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # fields come from env/.env
