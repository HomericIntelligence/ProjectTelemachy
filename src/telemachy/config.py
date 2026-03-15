"""Configuration settings loaded from environment variables or .env file."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings for ProjectTelemachy, loaded from env / .env file."""

    maestro_url: str
    maestro_api_key: str
    nats_url: str

    def __init__(self) -> None:
        self.maestro_url = os.environ.get("MAESTRO_URL", "http://172.20.0.1:23000")
        self.maestro_api_key = os.environ.get("MAESTRO_API_KEY", "")
        self.nats_url = os.environ.get("NATS_URL", "nats://localhost:4222")


settings = Settings()
