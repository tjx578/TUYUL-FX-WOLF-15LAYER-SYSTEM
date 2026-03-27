"""Ingest service health, readiness, metrics, and tick deduplication helpers.

Extracted from ingest_service.py for maintainability.
"""

from __future__ import annotations

import os
from time import time
from typing import Any

from loguru import logger

from core.health_probe import HealthProbe
from core.metrics import (
    INGEST_CACHE_MODE,
    INGEST_FRESH_PAIRS,
    INGEST_HEARTBEAT_AGE_SECONDS,
    INGEST_WS_CONNECTED,
)

# ── Health probe for container orchestration ──────────────────────
_INGEST_HEALTH_PORT = int(os.getenv("INGEST_HEALTH_PORT") or os.getenv("PORT", "8082"))
health_probe: HealthProbe = HealthProbe(port=_INGEST_HEALTH_PORT, service_name="ingest")
ingest_ready = False
ingest_degraded = False

# ── Producer state ────────────────────────────────────────────────
producer_present = False
producer_last_heartbeat_ts = 0.0

# ── Per-pair tick tracking ────────────────────────────────────────
pair_last_tick_ts: dict[str, float] = {}
pair_last_tick_fingerprint: dict[str, tuple[float, float]] = {}

_PRODUCER_FRESHNESS_SEC = max(5.0, float(os.getenv("INGEST_PRODUCER_FRESHNESS_SEC", "20")))
_WS_CONNECT_GRACE_SEC = float(os.getenv("INGEST_WS_CONNECT_GRACE_SEC", "45"))
_CACHE_MODES = ("unknown", "warmup", "stale_cache", "failed_no_cache")


def fresh_pair_count() -> int:
    now_ts = time()
    fresh = 0
    for last_tick_ts in pair_last_tick_ts.values():
        if last_tick_ts > 0 and (now_ts - last_tick_ts) <= _PRODUCER_FRESHNESS_SEC:
            fresh += 1
    return fresh


def mark_pair_tick(symbol: str, ts: float | None = None) -> None:
    pair = str(symbol).strip().upper()
    if not pair:
        return
    pair_last_tick_ts[pair] = time() if ts is None else float(ts)


def set_cache_mode(mode: str) -> None:
    selected = str(mode).strip().lower() or "unknown"
    for cache_mode in _CACHE_MODES:
        INGEST_CACHE_MODE.labels(mode=cache_mode).set(1.0 if cache_mode == selected else 0.0)
    health_probe.set_detail("cache_mode", selected)


def emit_ingest_runtime_metrics(connected: bool) -> None:
    heartbeat_age = max(0.0, time() - producer_last_heartbeat_ts) if producer_last_heartbeat_ts > 0 else float("inf")
    fresh_pairs = fresh_pair_count()

    INGEST_WS_CONNECTED.set(1.0 if connected else 0.0)
    INGEST_FRESH_PAIRS.set(float(fresh_pairs))
    INGEST_HEARTBEAT_AGE_SECONDS.set(heartbeat_age if heartbeat_age != float("inf") else 9.99e8)

    health_probe.set_detail("producer_present", "1" if connected else "0")
    health_probe.set_detail("producer_fresh", "1" if producer_fresh() else "0")
    health_probe.set_detail(
        "producer_heartbeat_age_sec", f"{heartbeat_age if heartbeat_age != float('inf') else 0.0:.2f}"
    )
    health_probe.set_detail("fresh_pairs", str(fresh_pairs))


def is_duplicate_pair_tick(symbol: str, price: float, ts: float) -> bool:
    """Return True when tick fingerprint matches the last accepted tick."""
    pair = str(symbol).strip().upper()
    if not pair:
        return False
    fingerprint = (float(ts), float(price))
    if pair_last_tick_fingerprint.get(pair) == fingerprint:
        return True
    pair_last_tick_fingerprint[pair] = fingerprint
    return False


def producer_fresh() -> bool:
    if producer_last_heartbeat_ts <= 0:
        return False
    return (time() - producer_last_heartbeat_ts) <= _PRODUCER_FRESHNESS_SEC


def update_producer_health(connected: bool) -> None:
    global producer_present, producer_last_heartbeat_ts
    producer_present = connected
    if connected:
        producer_last_heartbeat_ts = time()


def ingest_readiness() -> bool:
    """Readiness gate with grace period for freshly-connected WS."""
    base_ready = ingest_ready or ingest_degraded
    if not base_ready:
        return False

    is_fresh = producer_present and producer_fresh()
    if not is_fresh:
        return False

    pairs_ready = fresh_pair_count() > 0
    if pairs_ready:
        return True

    # Grace period: WS just connected, waiting for first tick
    if producer_last_heartbeat_ts > 0:
        ws_age = time() - producer_last_heartbeat_ts
        if ws_age <= _WS_CONNECT_GRACE_SEC:
            logger.debug(
                "[Readiness] WS fresh (age=%.1fs) — grace window active, menunggu tick pertama masuk",
                ws_age,
            )
            return True

    return False


def set_startup_mode(
    *,
    mode: str,
    warmup_results: dict[str, dict[str, list[dict[str, Any]]]],
    redis_has_data: bool,
) -> None:
    global ingest_ready, ingest_degraded

    set_cache_mode(mode)

    if mode == "warmup":
        ingest_ready = True
        ingest_degraded = False
        health_probe.set_detail("warmup", "complete")
        return

    if mode == "stale_cache":
        ingest_ready = False
        ingest_degraded = True
        health_probe.set_detail("warmup", "skipped_redis_cache")
        return

    if not warmup_results and not redis_has_data:
        ingest_ready = False
        ingest_degraded = False
        health_probe.set_detail("warmup", "failed_no_cache")
        logger.error(
            "[Ingest] Warmup failed and no stale cache available — service will remain NOT READY",
        )


health_probe.set_readiness_check(ingest_readiness)
