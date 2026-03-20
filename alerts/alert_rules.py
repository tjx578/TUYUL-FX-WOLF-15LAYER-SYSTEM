"""
Alert Rules
Controls which events produce alerts and their routing/thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Event-level on/off gates ─────────────────────────────────────────────────

ALERT_RULES: dict[str, bool] = {
    "L12_PASSED": True,
    "L12_REJECTED": True,
    "ORDER_PLACED": True,
    "ORDER_CANCELLED": True,
    "ORDER_EXPIRED": True,
    "ORDER_FILLED": True,
    "DRAWDOWN_WARNING": True,
    "SYSTEM_VIOLATION": True,
    "PRICE_DRIFT": True,
    "M15_COLD_START": True,
    "SLO_THRESHOLD_BREACH": True,
    # ── New comprehensive rules ──
    "FEED_STALE": True,
    "FEED_RECONNECT": True,
    "DRAWDOWN_CRITICAL": True,
    "DAILY_LOSS_WARNING": True,
    "DAILY_LOSS_CRITICAL": True,
    "KILL_SWITCH_TRIPPED": True,
    "CIRCUIT_BREAKER_OPEN": True,
    "PIPELINE_LATENCY_HIGH": True,
    "HEARTBEAT_ABSENT": True,
    "MASS_FEED_STALENESS": True,
}


# ── Threshold config ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AlertThresholds:
    """Centralized alert thresholds for the Wolf-15 trading system."""

    # Feed staleness (seconds since last tick)
    feed_stale_warning_seconds: float = 15.0
    feed_stale_critical_seconds: float = 30.0
    heartbeat_absent_seconds: float = 20.0
    mass_staleness_min_symbols: int = 4
    mass_staleness_ratio: float = 0.6

    # Drawdown thresholds (percentage of balance)
    daily_loss_warning_percent: float = 3.0
    daily_loss_critical_percent: float = 4.0
    max_drawdown_warning_percent: float = 6.0
    max_drawdown_critical_percent: float = 8.0

    # Pipeline latency (seconds)
    pipeline_latency_warning_seconds: float = 2.0
    tick_to_verdict_critical_seconds: float = 5.0

    # Redis stream lag (seconds)
    redis_lag_warning_seconds: float = 1.0


DEFAULT_THRESHOLDS = AlertThresholds()
