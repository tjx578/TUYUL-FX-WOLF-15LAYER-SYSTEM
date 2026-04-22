"""Ingest service health, readiness, metrics, and tick deduplication helpers.

Extracted from ingest_service.py for maintainability.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from time import time
from typing import Any

from loguru import logger

from core.health_probe import HealthProbe
from core.metrics import (
    INGEST_CACHE_MODE,
    INGEST_FRESH_PAIRS,
    INGEST_HEARTBEAT_AGE_SECONDS,
    INGEST_TICKS_PER_PAIR,
    INGEST_WS_CONNECTED,
)
from ingest.dependencies import _pair_last_tick_ts as pair_last_tick_ts

# ── Health probe for container orchestration ──────────────────────
_INGEST_HEALTH_PORT = int(os.getenv("INGEST_HEALTH_PORT") or os.getenv("PORT", "8082"))
health_probe: HealthProbe = HealthProbe(port=_INGEST_HEALTH_PORT, service_name="ingest")
ingest_ready = False
ingest_degraded = False
startup_mode = "unknown"
enabled_symbol_count = 0
_last_logged_ingest_state = ""
_last_logged_reason = ""
_last_logged_blocked_by = ""

# ── Producer state ────────────────────────────────────────────────
producer_present = False
producer_last_heartbeat_ts = 0.0

# ── Per-pair tick tracking ────────────────────────────────────────
# Use the same receipt-time map as REST fallback silence detection so
# readiness, health reporting, and fallback logic cannot drift apart.
pair_last_tick_fingerprint: dict[str, tuple[tuple[int, float], float]] = {}

_PRODUCER_FRESHNESS_SEC = max(5.0, float(os.getenv("INGEST_PRODUCER_FRESHNESS_SEC", "20")))
# Ticks with same exchange fingerprint arriving within this window are true duplicates.
# Beyond this window, same-fingerprint ticks are treated as separate events.
_DEDUP_REFRACTORY_S = float(os.getenv("INGEST_DEDUP_REFRACTORY_S", "0.05"))
_WS_CONNECT_GRACE_SEC = float(os.getenv("INGEST_WS_CONNECT_GRACE_SEC", "45"))
_READY_MIN_FRESH_PAIR_RATIO = min(
    1.0,
    max(0.0, float(os.getenv("INGEST_READY_MIN_FRESH_PAIR_RATIO", "0.85"))),
)
_CACHE_MODES = ("unknown", "warmup", "stale_cache", "failed_no_cache")


@dataclass(frozen=True)
class IngestReadinessSnapshot:
    startup_mode: str
    ws_connected: bool
    producer_present: bool
    producer_fresh: bool
    fresh_pairs: int
    total_pairs: int


def _min_ready_pairs(total_pairs: int) -> int:
    total = max(0, int(total_pairs))
    if total <= 1:
        return total
    return max(1, min(total, int(total * _READY_MIN_FRESH_PAIR_RATIO + 0.999999)))


def compute_ingest_readiness(snapshot: IngestReadinessSnapshot) -> dict[str, Any]:
    runtime_ready_allowed = snapshot.startup_mode != "failed_no_cache"
    fresh_pair_target = _min_ready_pairs(snapshot.total_pairs)
    fresh_pairs_ready = snapshot.fresh_pairs >= fresh_pair_target
    producer_ready = snapshot.producer_present and snapshot.producer_fresh

    blocked_by: list[str] = []
    if not runtime_ready_allowed:
        blocked_by.append("startup_not_bootstrapped")
    if not producer_ready:
        blocked_by.append("producer_not_fresh")
    if not fresh_pairs_ready:
        blocked_by.append("fresh_pairs_below_threshold")

    if runtime_ready_allowed and snapshot.ws_connected and producer_ready and fresh_pairs_ready:
        return {
            "ready": True,
            "degraded": False,
            "ingest_state": "LIVE",
            "market_data_mode": "WS_PRIMARY",
            "reason": "live_ws_ready",
            "blocked_by": [],
            "fresh_pair_target": fresh_pair_target,
        }

    if runtime_ready_allowed and not snapshot.ws_connected:
        return {
            "ready": False,
            "degraded": True,
            "ingest_state": "DEGRADED_REST_FALLBACK",
            "market_data_mode": "REST_DEGRADED",
            "reason": "rest_fallback_ready_but_ws_down",
            "blocked_by": blocked_by,
            "fresh_pair_target": fresh_pair_target,
        }

    return {
        "ready": False,
        "degraded": runtime_ready_allowed,
        "ingest_state": "DEGRADED" if runtime_ready_allowed else "NOT_READY",
        "market_data_mode": "WS_PRIMARY" if snapshot.ws_connected else "REST_DEGRADED",
        "reason": "readiness_conditions_not_met" if runtime_ready_allowed else "bootstrap_not_ready",
        "blocked_by": blocked_by,
        "fresh_pair_target": fresh_pair_target,
    }


def set_enabled_symbol_count(count: int) -> None:
    global enabled_symbol_count
    enabled_symbol_count = max(0, int(count))


def market_data_mode(*, ws_connected: bool) -> str:
    return "WS_PRIMARY" if ws_connected else "REST_DEGRADED"


def current_ingest_state(*, ws_connected: bool) -> str:
    return build_runtime_snapshot(ws_connected=ws_connected)["ingest_state"]


def build_runtime_snapshot(*, ws_connected: bool) -> dict[str, Any]:
    fresh_pairs = fresh_pair_count()
    readiness = compute_ingest_readiness(
        IngestReadinessSnapshot(
            startup_mode=startup_mode,
            ws_connected=ws_connected,
            producer_present=producer_present,
            producer_fresh=producer_fresh(),
            fresh_pairs=fresh_pairs,
            total_pairs=enabled_symbol_count,
        )
    )
    return {
        "ingest_state": readiness["ingest_state"],
        "market_data_mode": readiness["market_data_mode"],
        "startup_mode": startup_mode,
        "ready": readiness["ready"],
        "degraded": readiness["degraded"],
        "ws_connected": ws_connected,
        "rest_fallback_active": not ws_connected,
        "producer_present": producer_present,
        "producer_fresh": readiness["reason"] == "live_ws_ready" or producer_fresh(),
        "symbols_ready": fresh_pairs,
        "symbols_total": enabled_symbol_count,
        "fresh_pair_target": readiness["fresh_pair_target"],
        "reason": readiness["reason"],
        "blocked_by": readiness["blocked_by"],
    }


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
    # Freshness is based on local receipt time, not provider event time.
    # The optional ts is kept for call-site compatibility only.
    _ = ts
    pair_last_tick_ts[pair] = time()
    INGEST_TICKS_PER_PAIR.labels(symbol=pair).inc()


def set_cache_mode(mode: str) -> None:
    selected = str(mode).strip().lower() or "unknown"
    for cache_mode in _CACHE_MODES:
        INGEST_CACHE_MODE.labels(mode=cache_mode).set(1.0 if cache_mode == selected else 0.0)
    health_probe.set_detail("cache_mode", selected)


def emit_ingest_runtime_metrics(connected: bool) -> None:
    heartbeat_age = max(0.0, time() - producer_last_heartbeat_ts) if producer_last_heartbeat_ts > 0 else float("inf")
    snapshot = build_runtime_snapshot(ws_connected=connected)
    fresh_pairs = int(snapshot["symbols_ready"])

    INGEST_WS_CONNECTED.set(1.0 if connected else 0.0)
    INGEST_FRESH_PAIRS.set(float(fresh_pairs))
    INGEST_HEARTBEAT_AGE_SECONDS.set(heartbeat_age if heartbeat_age != float("inf") else 9.99e8)

    health_probe.set_detail("producer_present", "1" if connected else "0")
    health_probe.set_detail("producer_fresh", "1" if producer_fresh() else "0")
    health_probe.set_detail(
        "producer_heartbeat_age_sec", f"{heartbeat_age if heartbeat_age != float('inf') else 0.0:.2f}"
    )
    health_probe.set_detail("fresh_pairs", str(fresh_pairs))
    health_probe.set_detail("fresh_pair_target", str(snapshot["fresh_pair_target"]))
    health_probe.set_detail("ingest_state", str(snapshot["ingest_state"]))
    health_probe.set_detail("market_data_mode", str(snapshot["market_data_mode"]))
    health_probe.set_detail("readiness_reason", str(snapshot["reason"]))
    health_probe.set_detail("readiness_blocked_by", ",".join(str(item) for item in snapshot["blocked_by"]))
    health_probe.set_detail("rest_fallback_active", "1" if snapshot["rest_fallback_active"] else "0")
    health_probe.set_detail("symbols_ready", str(snapshot["symbols_ready"]))
    health_probe.set_detail("symbols_total", str(snapshot["symbols_total"]))
    health_probe.set_detail("ws_connected", "1" if snapshot["ws_connected"] else "0")
    _log_ingest_transition(snapshot)


def _log_ingest_transition(snapshot: dict[str, Any]) -> None:
    global _last_logged_blocked_by, _last_logged_ingest_state, _last_logged_reason

    blocked_by = ",".join(str(item) for item in snapshot["blocked_by"])
    state_changed = snapshot["ingest_state"] != _last_logged_ingest_state
    reason_changed = snapshot["reason"] != _last_logged_reason
    blockers_changed = blocked_by != _last_logged_blocked_by

    if state_changed:
        logger.info(
            "[IngestTransition] {} -> {} reason={} ws_connected={} producer_fresh={} fresh_pairs={}/{} target={} startup_mode={}",
            _last_logged_ingest_state or "UNKNOWN",
            snapshot["ingest_state"],
            snapshot["reason"],
            snapshot["ws_connected"],
            snapshot["producer_fresh"],
            snapshot["symbols_ready"],
            snapshot["symbols_total"],
            snapshot["fresh_pair_target"],
            snapshot["startup_mode"],
        )
    elif reason_changed or blockers_changed:
        logger.info(
            "[IngestReadinessBlocked] state={} reason={} blocked_by={} ws_connected={} producer_fresh={} fresh_pairs={}/{} target={} startup_mode={}",
            snapshot["ingest_state"],
            snapshot["reason"],
            blocked_by or "none",
            snapshot["ws_connected"],
            snapshot["producer_fresh"],
            snapshot["symbols_ready"],
            snapshot["symbols_total"],
            snapshot["fresh_pair_target"],
            snapshot["startup_mode"],
        )

    _last_logged_ingest_state = str(snapshot["ingest_state"])
    _last_logged_reason = str(snapshot["reason"])
    _last_logged_blocked_by = blocked_by


def is_duplicate_pair_tick(symbol: str, price: float, ts: float) -> bool:
    """Return True when tick fingerprint matches the last accepted tick.

    Uses ms-precision timestamp + refractory window to avoid aggressively
    deduplicating legitimate ticks that share the same second-precision
    exchange timestamp on low-volatility pairs (e.g. NZDUSD).
    """
    pair = str(symbol).strip().upper()
    if not pair:
        return False
    ts_ms = round(ts * 1000)
    price_r = round(price, 8)
    fingerprint = (ts_ms, price_r)
    now = time()
    prev = pair_last_tick_fingerprint.get(pair)
    if prev is not None:
        prev_fp, prev_local = prev
        if prev_fp == fingerprint and (now - prev_local) < _DEDUP_REFRACTORY_S:
            return True
    pair_last_tick_fingerprint[pair] = (fingerprint, now)
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
    snapshot = build_runtime_snapshot(ws_connected=producer_present)
    if snapshot["ready"]:
        return True

    if startup_mode == "failed_no_cache":
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
    global ingest_ready, ingest_degraded, startup_mode

    startup_mode = str(mode).strip().lower() or "unknown"
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
