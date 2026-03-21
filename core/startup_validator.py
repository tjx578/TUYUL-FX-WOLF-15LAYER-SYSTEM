"""Startup validator for wolf15-engine.

Checks critical prerequisites before the analysis loop begins.
Fails fast with clear error messages rather than let the engine run
in a broken state.

Zone: core/ — startup utility.  No execution or analysis side-effects.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from loguru import logger

__all__ = ["StartupCheckResult", "validate_engine_startup"]


@dataclass
class StartupCheckResult:
    """Aggregated result of all startup checks."""

    ok: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def _check_redis_url(result: StartupCheckResult) -> None:
    """Ensure a Redis connection target is configured."""
    redis_url = os.getenv("REDIS_URL", "").strip()
    redis_private_url = os.getenv("REDIS_PRIVATE_URL", "").strip()
    redis_host = os.getenv("REDIS_HOST", "").strip()
    redis_host_railway = os.getenv("REDISHOST", "").strip()

    if not redis_url and not redis_private_url and not redis_host and not redis_host_railway:
        result.fail(
            "No Redis connection configured. "
            "Set REDIS_URL, REDIS_PRIVATE_URL, or REDIS_HOST/REDIS_PORT "
            "(Railway also accepts REDISHOST/REDISPORT/REDISPASSWORD)."
        )


def _check_context_mode(result: StartupCheckResult) -> None:
    """Validate CONTEXT_MODE value."""
    mode = os.getenv("CONTEXT_MODE", "local").strip().lower()
    valid_modes = {"local", "redis"}
    if mode not in valid_modes:
        result.fail(f"Invalid CONTEXT_MODE='{mode}'. Must be one of: {valid_modes}")


def _check_run_mode(result: StartupCheckResult) -> None:
    """Validate RUN_MODE value."""
    mode = os.getenv("RUN_MODE", "all").strip().lower()
    valid_modes = {"all", "engine-only", "ingest-only", "api-only"}
    if mode not in valid_modes:
        result.fail(f"Invalid RUN_MODE='{mode}'. Must be one of: {valid_modes}")


def _check_enabled_symbols(result: StartupCheckResult) -> None:
    """Ensure at least one trading pair is configured."""
    try:
        from config_loader import get_enabled_symbols

        symbols = get_enabled_symbols()
        if not symbols:
            result.fail("No trading pairs configured. " "Check config/pairs.yaml or WOLF15_PAIRS env var.")
    except Exception as exc:
        result.fail(f"Failed to load enabled symbols: {exc}")


def _check_jwt_secret(result: StartupCheckResult) -> None:
    """Warn if JWT secret is missing or weak (API auth will fail)."""
    secret = os.getenv("DASHBOARD_JWT_SECRET", "").strip() or os.getenv("JWT_SECRET", "").strip()
    forbidden = {"CHANGE_ME", "CHANGE_ME_SUPER_SECRET", "CHANGE_ME_TO_RANDOM_STRING"}
    if not secret:
        result.warn("DASHBOARD_JWT_SECRET not set — JWT auth will fail closed.")
    elif secret in forbidden or len(secret) < 32:
        result.warn("DASHBOARD_JWT_SECRET is weak (< 32 chars or placeholder). " "Use: openssl rand -hex 32")


def _check_database_url(result: StartupCheckResult) -> None:
    """Warn if DATABASE_URL is missing (journal persistence won't work)."""
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        result.warn(
            "DATABASE_URL not set — PostgreSQL persistence disabled. "
            "Journal audit trail and candle backup won't work."
        )


async def _check_redis_connectivity(result: StartupCheckResult) -> None:
    """Attempt a Redis PING to verify connectivity."""
    try:
        from redis.asyncio import Redis as AsyncRedis

        from infrastructure.redis_url import get_redis_url

        redis_url = get_redis_url()
        client: AsyncRedis = AsyncRedis.from_url(redis_url)
        try:
            await client.ping()  # type: ignore[misc]
        finally:
            await client.aclose()
    except Exception as exc:
        result.fail(f"Redis connectivity check failed: {exc}")


def validate_engine_startup(*, check_redis_ping: bool = False) -> StartupCheckResult:
    """Run all startup validation checks synchronously.

    Parameters
    ----------
    check_redis_ping:
        If True, also performs an async Redis PING check.
        Requires a running event loop (use ``validate_engine_startup_async``
        instead when calling from async context).

    Returns
    -------
    StartupCheckResult with ok=True if all critical checks pass.
    """
    result = StartupCheckResult()

    _check_redis_url(result)
    _check_context_mode(result)
    _check_run_mode(result)
    _check_enabled_symbols(result)
    _check_jwt_secret(result)
    _check_database_url(result)

    for w in result.warnings:
        logger.warning("[StartupValidator] {}", w)
    for e in result.errors:
        logger.error("[StartupValidator] {}", e)

    if result.ok:
        logger.info("[StartupValidator] All checks passed")
    else:
        logger.error(
            "[StartupValidator] %d error(s), %d warning(s) — engine may not function correctly",
            len(result.errors),
            len(result.warnings),
        )

    return result


async def validate_engine_startup_async() -> StartupCheckResult:
    """Run all startup checks including async Redis ping."""
    result = StartupCheckResult()

    _check_redis_url(result)
    _check_context_mode(result)
    _check_run_mode(result)
    _check_enabled_symbols(result)
    _check_jwt_secret(result)
    _check_database_url(result)

    # Only attempt ping if Redis URL is configured
    if result.ok:
        await _check_redis_connectivity(result)

    for w in result.warnings:
        logger.warning("[StartupValidator] {}", w)
    for e in result.errors:
        logger.error("[StartupValidator] {}", e)

    if result.ok:
        logger.info("[StartupValidator] All checks passed (with Redis ping)")
    else:
        logger.error(
            "[StartupValidator] %d error(s), %d warning(s)",
            len(result.errors),
            len(result.warnings),
        )

    return result
