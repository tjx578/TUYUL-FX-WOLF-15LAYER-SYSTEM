"""
Dashboard API dependencies.

Provides shared dependency-injection helpers for FastAPI route handlers:
- Database session management
- Configuration access
- Risk guard access
- Authentication helpers (placeholder)

Authority note: Dashboard is an account/risk governor + ledger.
It never overrides Layer-12 verdicts or computes market direction.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from fastapi import Depends, Header, HTTPException, status

if TYPE_CHECKING:
    from sqlalchemy.orm import (  # pyright: ignore[reportMissingImports]
        sessionmaker as SQLAlchemySessionmaker,  # type: ignore[reportMissingImports]  # noqa: N812
    )

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class Settings:
    """Minimal application settings pulled from environment."""

    def __init__(self) -> None:
        super().__init__()
        self.database_url: str = os.getenv("DATABASE_URL", "sqlite:///./dashboard.db")
        self.redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.api_key: str = os.getenv("DASHBOARD_API_KEY", "")
        self.debug: bool = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
        self.prop_firm_profile: str = os.getenv("PROP_FIRM_PROFILE", "default")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings (singleton)."""
    return Settings()


# ---------------------------------------------------------------------------
# Database session (lazy — only activated when an engine is configured)
# ---------------------------------------------------------------------------

_SessionLocal: SQLAlchemySessionmaker[Any] | None = None  # Will be a sessionmaker instance when DB is initialised


def _init_db(settings: Settings) -> SQLAlchemySessionmaker[Any] | None: # pyright: ignore[reportUnknownParameterType]
    """Lazily initialise SQLAlchemy engine + session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        try:
            from sqlalchemy import create_engine  # type: ignore[import-untyped]
            from sqlalchemy.engine import Engine  # type: ignore[import-untyped]  # noqa: F401
            from sqlalchemy.orm import sessionmaker  # type: ignore[import-untyped]

            engine = create_engine(  # type: ignore[var-annotated]
                settings.database_url,
                connect_args=(
                    {"check_same_thread": False}
                    if settings.database_url.startswith("sqlite")
                    else {}
                ),
            )
            _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) # pyright: ignore[reportUnknownVariableType]
        except ImportError:
            # SQLAlchemy not installed — return None so callers can guard
            _SessionLocal = None
    return _SessionLocal # pyright: ignore[reportUnknownVariableType]


def get_db(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> Generator[Any, None, None]:
    """
    Yield a database session for request scope.

    Raises 503 if the database layer is not available.
    """
    session_factory = _init_db(settings) # pyright: ignore[reportUnknownVariableType]
    if session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database layer not available",
        )
    db: Any = session_factory() # pyright: ignore[reportUnknownVariableType]
    try:
        yield db
    finally:
        db.close()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Prop-firm risk guard
# ---------------------------------------------------------------------------

def get_risk_guard(settings: Settings = Depends(get_settings)) -> Any:  # noqa: B008
    """
    Return the prop-firm guard instance for the active profile.

    Uses ``risk.prop_firm`` module. Returns *None* if the module is
    not yet importable (allows graceful degradation during development).
    """
    try:
        from risk.prop_firm import PropFirmGuard
        return PropFirmGuard()
    except (ImportError, Exception):
        return None


# ---------------------------------------------------------------------------
# Authentication / API-key verification (simple bearer-key approach)
# ---------------------------------------------------------------------------

def verify_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> str:
    """
    Validate the caller-supplied API key against ``DASHBOARD_API_KEY``.

    If no key is configured (empty string), authentication is **skipped**
    to ease local development.  In production, always set ``DASHBOARD_API_KEY``.
    """
    expected = settings.api_key
    if not expected:
        # No key configured → auth disabled (dev mode)
        return "anonymous"
    if x_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return x_api_key # type: ignore


# ---------------------------------------------------------------------------
# Convenience re-exports so routes can do:
#   from dashboard.api.deps import get_db, get_settings, verify_api_key
# ---------------------------------------------------------------------------

__all__ = [
    "Settings",
    "get_settings",
    "get_db",
    "get_risk_guard",
    "verify_api_key",
]
