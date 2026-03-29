"""Configuration settings loaded from environment variables or .env file."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings for ProjectTelemachy."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    agamemnon_url: str = "http://localhost:8080"
    agamemnon_api_key: str = ""
    nats_url: str = "nats://localhost:4222"


settings = Settings()
