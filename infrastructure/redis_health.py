"""Redis connection pool health monitoring.

Provides periodic pool-status logging and a health-check function that
can be called from startup probes, heartbeat loops, or API endpoints.

Zone: infrastructure/ — observability glue.  No analysis or execution logic.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _compute_pool_metrics(pool: object) -> tuple[int, int, int, int, int]:
    """Return (available, in_use, created, max_conns, headroom)."""
    available = len(getattr(pool, "_available_connections", []))
    in_use = len(getattr(pool, "_in_use_connections", []))
    created = available + in_use
    max_conns = int(getattr(pool, "max_connections", 0) or 0)
    headroom = max(0, max_conns - in_use) if max_conns > 0 else available
    return available, in_use, created, max_conns, headroom


async def check_redis_pool_health() -> dict[str, object]:
    """Check async Redis pool status and return a health report.

    Returns a dict with keys:
        healthy (bool): True if ping succeeds and pool is not exhausted.
        pool_created (int): Number of connections currently created.
        pool_available (int): Number of idle connections available.
        pool_in_use (int): Connections currently checked-out.
        pool_max (int): Maximum connections allowed.
    """
    from infrastructure.redis_client import _manager  # noqa: PLC0415

    pool = _manager._pool  # noqa: SLF001
    if pool is None:
        # Lazily initialise if no earlier code path created the pool yet
        try:
            pool = await _manager.get_pool()
        except Exception as exc:
            logger.warning("[RedisHealth] Pool initialisation failed: %s", exc)
            return {"healthy": False, "reason": f"pool_init_failed: {exc}"}

    # ConnectionPool internals: _available_connections (idle) + _in_use_connections (active)
    available, in_use, created, max_conns, headroom = _compute_pool_metrics(pool)

    report: dict[str, object] = {
        "pool_created": created,
        "pool_available": available,
        "pool_in_use": in_use,
        "pool_max": max_conns,
        "pool_headroom": headroom,
    }

    # Test actual connectivity
    try:
        healthy = await _manager.health_check()
    except Exception:
        healthy = False

    report["healthy"] = healthy

    if not healthy:
        logger.error("[RedisHealth] Pool unhealthy — ping failed | %s", report)
    elif headroom < 3 and max_conns > 0:
        logger.warning(
            "[RedisHealth] Low available connections: %d/%d (in_use=%d, idle=%d, created=%d)",
            headroom,
            max_conns,
            in_use,
            available,
            created,
        )
    else:
        logger.info(
            "[RedisHealth] Pool status: headroom=%d in_use=%d max=%d idle=%d created=%d",
            headroom,
            in_use,
            max_conns,
            available,
            created,
        )

    return report


def check_sync_redis_pool_health() -> dict[str, object]:
    """Check sync Redis pool status (storage/redis_client.py singleton).

    Returns a dict similar to the async variant.
    """
    try:
        from storage.redis_client import RedisClient  # noqa: PLC0415

        client = RedisClient()
        pool = client._pool  # noqa: SLF001

        available, in_use, created, max_conns, headroom = _compute_pool_metrics(pool)

        healthy = client.ping()

        report: dict[str, object] = {
            "healthy": healthy,
            "pool_created": created,
            "pool_available": available,
            "pool_in_use": in_use,
            "pool_max": max_conns,
            "pool_headroom": headroom,
        }

        if headroom < 3 and max_conns > 0:
            logger.warning(
                "[RedisHealth:sync] Low available connections: %d/%d (in_use=%d, idle=%d, created=%d)",
                headroom,
                max_conns,
                in_use,
                available,
                created,
            )

        return report
    except Exception as exc:
        logger.error("[RedisHealth:sync] Health check failed: %s", exc)
        return {"healthy": False, "reason": str(exc)}
