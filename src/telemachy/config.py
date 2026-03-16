"""Configuration settings loaded from environment variables or .env file."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings for ProjectTelemachy, loaded from env / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    maestro_url: str = "http://172.20.0.1:23000"
    maestro_api_key: str = ""
    nats_url: str = "nats://localhost:4222"


settings = Settings()
