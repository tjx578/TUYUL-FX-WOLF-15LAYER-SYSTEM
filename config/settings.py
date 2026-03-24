"""Service-level runtime settings."""
from __future__ import annotations

from dataclasses import dataclass

from config.env import get_env


@dataclass(slots=True)
class ServiceSettings:
    redis_url: str | None = get_env("REDIS_URL")
    database_url: str | None = get_env("DATABASE_URL")
    log_level: str = (get_env("LOG_LEVEL", "INFO") or "INFO").upper()
    engine_mode: str = (get_env("ENGINE_MODE", "paper") or "paper").lower()
