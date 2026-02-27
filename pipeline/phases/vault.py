"""
Phase 7 — Vault Sync & Sovereignty Computation.

Computes the 3-component vault sync score and derives execution rights.
This is a pure function aside from infrastructure health checks.
Authority: Layer-12 is the SOLE CONSTITUTIONAL AUTHORITY.
"""

from __future__ import annotations

from typing import Any

try:
    from loguru import logger  # pyright: ignore[reportMissingImports]
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from pipeline.constants import get_vault_sync_thresholds, get_vault_sync_weights


def compute_vault_sync(
    synthesis: dict[str, Any],
    vault_checker: Any,
) -> dict[str, Any]:
    """Compute vault sync (3-component) + base sovereignty level.

    Vault sync formula: feed * 0.50 + redis * 0.30 + integrity * 0.20

    Note: Final sovereignty enforcement (including drift checks and
    verdict downgrades) is handled by L15MetaSovereigntyEngine.enforce_sovereignty().

    Args:
        synthesis: L12 synthesis dict (used to extract symbol).
        vault_checker: VaultHealthChecker instance (or None — will attempt
            lazy initialisation inside this function).

    Returns:
        dict with execution_rights, lot_multiplier, vault_sync, and
        component scores.
    """
    weights = get_vault_sync_weights()
    thresholds = get_vault_sync_thresholds()

    symbol = synthesis.get("pair", "")
    feed_freshness = 0.0
    redis_health = 0.0

    try:
        if vault_checker is None:
            from context.live_context_bus import LiveContextBus  # noqa: PLC0415
            from core.vault_health import VaultHealthChecker  # noqa: PLC0415
            from storage.redis_client import RedisClient  # noqa: PLC0415

            try:
                redis_client = RedisClient()
            except Exception as redis_err:
                logger.warning(
                    "[VaultSync] Redis client init failed: %s -- treating Redis as DOWN",
                    redis_err,
                )
                redis_client = None

            context_bus = LiveContextBus()
            vault_checker = VaultHealthChecker(
                redis_client=redis_client,
                context_bus=context_bus,
            )

        vault_report = vault_checker.check(
            symbols=[symbol] if symbol else [],
        )
        feed_freshness = vault_report.feed_freshness
        redis_health = vault_report.redis_health

        if vault_report.should_block_analysis:
            logger.warning(
                "[VaultSync] Vault health CRITICAL for %s -- %s",
                symbol,
                vault_report.details,
            )
        elif not vault_report.is_healthy:
            logger.warning(
                "[VaultSync] Vault health degraded for %s -- %s",
                symbol,
                vault_report.details,
            )
    except Exception as exc:
        logger.error(
            "[VaultSync] Vault health check FAILED for %s: %s -- defaulting to 0.0",
            symbol,
            exc,
        )
        feed_freshness = 0.0
        redis_health = 0.0

    meta_integrity = 1.0

    vault_sync = (
        feed_freshness * weights["feed"] + redis_health * weights["redis"] + meta_integrity * weights["integrity"]
    )

    if vault_sync >= thresholds["strict"]:
        execution_rights = "GRANTED"
        lot_multiplier = 1.0
    elif vault_sync >= thresholds["operational"]:
        execution_rights = "RESTRICTED"
        lot_multiplier = 0.7
    elif vault_sync >= thresholds["critical"]:
        execution_rights = "RESTRICTED"
        lot_multiplier = 0.5
    else:
        execution_rights = "REVOKED"
        lot_multiplier = 0.0

    return {
        "execution_rights": execution_rights,
        "lot_multiplier": lot_multiplier,
        "vault_sync": vault_sync,
        "feed_freshness": feed_freshness,
        "redis_health": redis_health,
        "meta_integrity": meta_integrity,
        "weights": weights,
        "thresholds": thresholds,
    }
