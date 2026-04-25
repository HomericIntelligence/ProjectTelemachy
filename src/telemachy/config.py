"""Configuration settings loaded from environment variables or .env file."""

from __future__ import annotations

from pathlib import Path

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
    workflows_dir: Path = Path("workflows")
    host_id: str = "hermes"
    require_tls: bool = False
    monitor_timeout_seconds: float = 3600.0
    monitor_max_polls: int = 7200


settings = Settings()
