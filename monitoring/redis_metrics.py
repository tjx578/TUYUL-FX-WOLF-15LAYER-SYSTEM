"""Redis observability metrics.

Metrics are refreshed from Redis INFO snapshots collected by API health
endpoints or other read-only probes. This module does not perform Redis I/O.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from core.metrics import Counter, Gauge, get_registry

_R = get_registry()
_LOCK = threading.Lock()
_LAST_COUNTER_SNAPSHOTS: dict[str, float] = {}

REDIS_USED_MEMORY_BYTES: Gauge = _R.gauge(
    "wolf_redis_used_memory_bytes",
    "Redis used memory in bytes",
)
REDIS_CONNECTED_CLIENTS: Gauge = _R.gauge(
    "wolf_redis_connected_clients",
    "Redis connected clients",
)
REDIS_BLOCKED_CLIENTS: Gauge = _R.gauge(
    "wolf_redis_blocked_clients",
    "Redis blocked clients",
)
REDIS_CLIENT_USED_RATIO: Gauge = _R.gauge(
    "wolf_redis_client_used_ratio",
    "Redis connected clients divided by maxclients",
)
REDIS_MEMORY_USED_RATIO: Gauge = _R.gauge(
    "wolf_redis_memory_used_ratio",
    "Redis used memory divided by maxmemory (0 when maxmemory is unlimited)",
)
REDIS_INSTANTANEOUS_INPUT_KBPS: Gauge = _R.gauge(
    "wolf_redis_instantaneous_input_kbps",
    "Redis instantaneous network input in KiB/s",
)
REDIS_INSTANTANEOUS_OUTPUT_KBPS: Gauge = _R.gauge(
    "wolf_redis_instantaneous_output_kbps",
    "Redis instantaneous network output in KiB/s",
)
REDIS_CLIENT_RECENT_MAX_INPUT_BUFFER_BYTES: Gauge = _R.gauge(
    "wolf_redis_client_recent_max_input_buffer_bytes",
    "Redis recent maximum client input buffer size in bytes",
)
REDIS_CLIENT_RECENT_MAX_OUTPUT_BUFFER_BYTES: Gauge = _R.gauge(
    "wolf_redis_client_recent_max_output_buffer_bytes",
    "Redis recent maximum client output buffer size in bytes",
)
REDIS_RDB_LAST_BGSAVE_STATUS: Gauge = _R.gauge(
    "wolf_redis_rdb_last_bgsave_status",
    "Redis RDB last BGSAVE status (1=ok, 0=not-ok)",
)
REDIS_RDB_LAST_BGSAVE_DURATION_SECONDS: Gauge = _R.gauge(
    "wolf_redis_rdb_last_bgsave_duration_seconds",
    "Redis RDB last BGSAVE duration in seconds",
)
REDIS_CHANGES_SINCE_LAST_SAVE: Gauge = _R.gauge(
    "wolf_redis_changes_since_last_save",
    "Redis changes since last successful persistence save",
)
REDIS_TOTAL_KEYS: Gauge = _R.gauge(
    "wolf_redis_total_keys",
    "Redis total keys across logical databases",
)
REDIS_EVICTED_KEYS_TOTAL: Counter = _R.counter(
    "wolf_redis_evicted_keys_total",
    "Redis evicted keys reported by INFO stats",
)
REDIS_EXPIRED_KEYS_TOTAL: Counter = _R.counter(
    "wolf_redis_expired_keys_total",
    "Redis expired keys reported by INFO stats",
)
REDIS_KEYSPACE_HITS_TOTAL: Counter = _R.counter(
    "wolf_redis_keyspace_hits_total",
    "Redis keyspace hits reported by INFO stats",
)
REDIS_KEYSPACE_MISSES_TOTAL: Counter = _R.counter(
    "wolf_redis_keyspace_misses_total",
    "Redis keyspace misses reported by INFO stats",
)
REDIS_REJECTED_CONNECTIONS_TOTAL: Counter = _R.counter(
    "wolf_redis_rejected_connections_total",
    "Redis rejected connections reported by INFO stats",
)


def _as_float(report: Mapping[str, object], key: str) -> float:
    value = report.get(key, 0.0)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _update_counter(metric: Counter, key: str, current_value: float) -> None:
    current = max(0.0, current_value)
    with _LOCK:
        previous = _LAST_COUNTER_SNAPSHOTS.get(key)
        delta = current if previous is None else current - previous
        _LAST_COUNTER_SNAPSHOTS[key] = current
    if delta > 0:
        metric.labels().inc(delta)


def update_redis_metrics(report: Mapping[str, object]) -> None:
    """Refresh Prometheus metrics from an extended Redis health report."""
    REDIS_USED_MEMORY_BYTES.labels().set(_as_float(report, "used_memory"))
    REDIS_CONNECTED_CLIENTS.labels().set(_as_float(report, "connected_clients"))
    REDIS_BLOCKED_CLIENTS.labels().set(_as_float(report, "blocked_clients"))
    REDIS_CLIENT_USED_RATIO.labels().set(_as_float(report, "client_used_ratio"))
    REDIS_MEMORY_USED_RATIO.labels().set(_as_float(report, "memory_used_ratio"))
    REDIS_INSTANTANEOUS_INPUT_KBPS.labels().set(_as_float(report, "instantaneous_input_kbps"))
    REDIS_INSTANTANEOUS_OUTPUT_KBPS.labels().set(_as_float(report, "instantaneous_output_kbps"))
    REDIS_CLIENT_RECENT_MAX_INPUT_BUFFER_BYTES.labels().set(_as_float(report, "client_recent_max_input_buffer"))
    REDIS_CLIENT_RECENT_MAX_OUTPUT_BUFFER_BYTES.labels().set(_as_float(report, "client_recent_max_output_buffer"))
    REDIS_RDB_LAST_BGSAVE_STATUS.labels().set(1.0 if str(report.get("rdb_last_bgsave_status", "")).lower() == "ok" else 0.0)
    REDIS_RDB_LAST_BGSAVE_DURATION_SECONDS.labels().set(_as_float(report, "rdb_last_bgsave_time_sec"))
    REDIS_CHANGES_SINCE_LAST_SAVE.labels().set(_as_float(report, "rdb_changes_since_last_save"))
    REDIS_TOTAL_KEYS.labels().set(_as_float(report, "total_keys"))

    _update_counter(REDIS_EVICTED_KEYS_TOTAL, "evicted_keys", _as_float(report, "evicted_keys"))
    _update_counter(REDIS_EXPIRED_KEYS_TOTAL, "expired_keys", _as_float(report, "expired_keys"))
    _update_counter(REDIS_KEYSPACE_HITS_TOTAL, "keyspace_hits", _as_float(report, "keyspace_hits"))
    _update_counter(REDIS_KEYSPACE_MISSES_TOTAL, "keyspace_misses", _as_float(report, "keyspace_misses"))
    _update_counter(REDIS_REJECTED_CONNECTIONS_TOTAL, "rejected_connections", _as_float(report, "rejected_connections"))
