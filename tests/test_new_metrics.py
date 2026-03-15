"""Tests for newly registered metrics in core/metrics.py.

Verifies that every new trading / feed / kill-switch metric exists in the
global registry and has the correct type and label set.
"""

from __future__ import annotations

import pytest

from core.metrics import (
    CIRCUIT_BREAKER_STATE,
    CIRCUIT_BREAKER_TRIPS,
    DAILY_LOSS_PERCENT,
    DRAWDOWN_MAX_PERCENT,
    FEED_RECONNECT_TOTAL,
    # Feed health
    FEED_STALE_TOTAL,
    # Kill switch
    KILL_SWITCH_ACTIVE,
    KILL_SWITCH_TRIPS_TOTAL,
    PNL_REALIZED_CURRENT,
    PNL_REALIZED_TOTAL,
    # Trading performance
    TRADES_TOTAL,
    WIN_RATE,
    Counter,
    Gauge,
    # Registry
    get_registry,
)


class TestNewMetricsExist:
    """Ensure every new metric is registered, typed correctly, and has expected labels."""

    @pytest.mark.parametrize("metric,expected_type,expected_labels", [
        (TRADES_TOTAL, Counter, ("symbol", "outcome")),
        (PNL_REALIZED_TOTAL, Counter, ("symbol",)),
        (PNL_REALIZED_CURRENT, Gauge, ("account_id",)),
        (WIN_RATE, Gauge, ("symbol",)),
        (DRAWDOWN_MAX_PERCENT, Gauge, ("account_id",)),
        (DAILY_LOSS_PERCENT, Gauge, ("account_id",)),
        (FEED_STALE_TOTAL, Counter, ("symbol",)),
        (FEED_RECONNECT_TOTAL, Counter, ("source",)),
        (CIRCUIT_BREAKER_STATE, Gauge, ("name",)),
        (CIRCUIT_BREAKER_TRIPS, Counter, ("name",)),
        (KILL_SWITCH_ACTIVE, Gauge, ()),
        (KILL_SWITCH_TRIPS_TOTAL, Counter, ("reason",)),
    ])
    def test_metric_type_and_labels(self, metric, expected_type, expected_labels):
        assert isinstance(metric, expected_type), (
            f"{metric.name} should be {expected_type.__name__}"
        )
        assert metric.label_names == expected_labels, (
            f"{metric.name}: labels {metric.label_names} != {expected_labels}"
        )


class TestMetricsInRegistry:
    """All new metrics are discoverable via the global registry."""

    def test_all_new_names_in_registry(self):
        registry = get_registry()
        names = registry._names
        expected_names = [
            "wolf_trades_total",
            "wolf_pnl_realized_total",
            "wolf_pnl_realized_current",
            "wolf_win_rate",
            "wolf_drawdown_max_percent",
            "wolf_daily_loss_percent",
            "wolf_feed_stale_total",
            "wolf_feed_reconnect_total",
            "wolf_circuit_breaker_state",
            "wolf_circuit_breaker_trips_total",
            "wolf_kill_switch_active",
            "wolf_kill_switch_trips_total",
        ]
        for name in expected_names:
            assert name in names, f"{name} missing from MetricsRegistry"


class TestLabellessGaugeOps:
    """Kill switch gauge (no labels) supports set/inc/dec directly."""

    def test_set_and_read(self):
        KILL_SWITCH_ACTIVE.set(1.0)
        assert KILL_SWITCH_ACTIVE._no_label is not None
        assert KILL_SWITCH_ACTIVE._no_label.value == 1.0
        KILL_SWITCH_ACTIVE.set(0.0)
        assert KILL_SWITCH_ACTIVE._no_label.value == 0.0
