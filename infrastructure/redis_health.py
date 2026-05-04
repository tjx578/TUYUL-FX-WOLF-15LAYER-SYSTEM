"""Redis connection pool health monitoring.

Provides periodic pool-status logging and a health-check function that
can be called from startup probes, heartbeat loops, or API endpoints.

Zone: infrastructure/ — observability glue.  No analysis or execution logic.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)


def _as_int(mapping: Mapping[str, object], key: str) -> int:
    value = mapping.get(key, 0)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _as_float(mapping: Mapping[str, object], key: str) -> float:
    value = mapping.get(key, 0.0)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _as_str(mapping: Mapping[str, object], key: str, default: str = "") -> str:
    value = mapping.get(key, default)
    if value is None:
        return default
    return str(value)


def _aggregate_keyspace(keyspace: Mapping[str, object]) -> dict[str, int]:
    total_keys = 0
    total_expires = 0
    db_count = 0
    for name, raw_value in keyspace.items():
        if not str(name).startswith("db") or not isinstance(raw_value, Mapping):
            continue
        db_count += 1
        total_keys += _as_int(raw_value, "keys")
        total_expires += _as_int(raw_value, "expires")
    return {
        "db_count": db_count,
        "total_keys": total_keys,
        "total_expires": total_expires,
    }


def build_extended_redis_report(
    *,
    pong: bool,
    stats: Mapping[str, object],
    clients: Mapping[str, object],
    memory: Mapping[str, object],
    persistence: Mapping[str, object],
    keyspace: Mapping[str, object],
    slowlog_len: int,
    latency_ms: float,
    timestamp: str,
) -> dict[str, object]:
    """Build a stable Redis runtime snapshot from INFO sections."""
    keyspace_totals = _aggregate_keyspace(keyspace)
    bgsave_status = _as_str(persistence, "rdb_last_bgsave_status", "unknown").lower()
    aof_rewrite_status = _as_str(persistence, "aof_last_bgrewrite_status", "unknown").lower()
    maxmemory = _as_int(memory, "maxmemory")
    used_memory = _as_int(memory, "used_memory")
    memory_headroom = max(0, maxmemory - used_memory) if maxmemory > 0 else 0
    memory_used_ratio = (used_memory / maxmemory) if maxmemory > 0 else 0.0
    maxclients = _as_int(clients, "maxclients")
    connected_clients = _as_int(clients, "connected_clients")
    client_used_ratio = (connected_clients / maxclients) if maxclients > 0 else 0.0

    return {
        "status": "ok" if pong else "degraded",
        "latency_ms": round(latency_ms, 2),
        "timestamp": timestamp,
        "connected_clients": connected_clients,
        "blocked_clients": _as_int(clients, "blocked_clients"),
        "maxclients": maxclients,
        "client_used_ratio": round(client_used_ratio, 4),
        "rejected_connections": _as_int(stats, "rejected_connections"),
        "total_connections_received": _as_int(stats, "total_connections_received"),
        "instantaneous_ops_per_sec": _as_int(stats, "instantaneous_ops_per_sec"),
        "instantaneous_input_kbps": round(_as_float(stats, "instantaneous_input_kbps"), 4),
        "instantaneous_output_kbps": round(_as_float(stats, "instantaneous_output_kbps"), 4),
        "client_recent_max_input_buffer": _as_int(clients, "client_recent_max_input_buffer"),
        "client_recent_max_output_buffer": _as_int(clients, "client_recent_max_output_buffer"),
        "slowlog_len": int(slowlog_len),
        "used_memory": used_memory,
        "used_memory_peak": _as_int(memory, "used_memory_peak"),
        "maxmemory": maxmemory,
        "memory_headroom_bytes": memory_headroom,
        "memory_used_ratio": round(memory_used_ratio, 4),
        "mem_fragmentation_ratio": round(_as_float(memory, "mem_fragmentation_ratio"), 4),
        "expired_keys": _as_int(stats, "expired_keys"),
        "evicted_keys": _as_int(stats, "evicted_keys"),
        "keyspace_hits": _as_int(stats, "keyspace_hits"),
        "keyspace_misses": _as_int(stats, "keyspace_misses"),
        "total_keys": keyspace_totals["total_keys"],
        "keyspace_db_count": keyspace_totals["db_count"],
        "keyspace_expires": keyspace_totals["total_expires"],
        "rdb_last_bgsave_status": bgsave_status,
        "rdb_last_bgsave_time_sec": _as_int(persistence, "rdb_last_bgsave_time_sec"),
        "rdb_changes_since_last_save": _as_int(persistence, "rdb_changes_since_last_save"),
        "aof_enabled": bool(_as_int(persistence, "aof_enabled")),
        "aof_last_bgrewrite_status": aof_rewrite_status,
        "total_commands_processed": _as_int(stats, "total_commands_processed"),
        "total_net_input_bytes": _as_int(stats, "total_net_input_bytes"),
        "total_net_output_bytes": _as_int(stats, "total_net_output_bytes"),
    }


def _compute_pool_metrics(pool: object) -> tuple[int, int, int, int, int]:
    """Return (available, in_use, created, max_conns, headroom)."""
    free_getter = getattr(pool, "_get_free_connections", None)
    in_use_getter = getattr(pool, "_get_in_use_connections", None)
    if callable(free_getter) and callable(in_use_getter):
        try:
            available = len(free_getter())
            in_use = len(in_use_getter())
            created = len(getattr(pool, "_connections", []))
        except Exception:
            available = len(getattr(pool, "_available_connections", []))
            in_use = len(getattr(pool, "_in_use_connections", []))
            created = available + in_use
    else:
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
