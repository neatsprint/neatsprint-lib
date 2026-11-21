"""12-factor settings shared by every service.

Each service subclasses :class:`ServiceSettings` and sets ``service_name``. Values come
from environment variables (case-insensitive) and, in local development, a `.env` file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "ci", "staging", "production"]


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = "service"
    environment: Environment = "local"
    log_level: str = "INFO"
    version: str = "0.1.0"

    database_url: str | None = None
    redis_url: str | None = None

    # Comma-separated list; parsed into a list by the validator below.
    cors_origins: str = "http://localhost:3000"

    # Set to false only in tests. Production must always validate tokens.
    auth_enabled: bool = True
    jwks_url: str | None = None
    jwt_issuer: str = "neatsprint-iam"
    jwt_audience: str = "neatsprint"

    otel_enabled: bool = False
    metrics_enabled: bool = True

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"
