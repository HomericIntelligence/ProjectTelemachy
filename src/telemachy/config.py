"""Configuration settings loaded from environment variables or .env file."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgamemnonClientKwargs(TypedDict):
    """Typed kwargs matching AgamemnonClient.__init__ parameters."""

    url: str
    api_key: str
    host_id: str
    require_tls: bool
    nats_url: str


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
    log_level: str = "INFO"
    default_workflow_timeout: float = 7200.0

    def client_kwargs(self) -> AgamemnonClientKwargs:
        """Return keyword arguments for constructing an AgamemnonClient.

        Both ``cli.run`` and ``executor.run_workflow`` must use this so that
        client construction stays DRY and all settings are applied uniformly.
        """
        return {
            "url": self.agamemnon_url,
            "api_key": self.agamemnon_api_key,
            "host_id": self.host_id,
            "require_tls": self.require_tls,
            "nats_url": self.nats_url,
        }


settings = Settings()
