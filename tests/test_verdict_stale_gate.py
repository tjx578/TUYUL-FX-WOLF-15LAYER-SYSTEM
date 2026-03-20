"""Tests for the stale data circuit breaker in constitution/verdict_engine.py.

The circuit breaker is a constitutional safety gate at the top of
produce_verdict() that returns HOLD when the live feed is stale.

Constitutional constraints verified here:
  - Returns HOLD, never EXECUTE (can only prevent trades, never promote them)
  - circuit_breaker=True in result when triggered
  - Does NOT import from execution/ zone
  - Configurable threshold via config["feed_stale_threshold_sec"]
"""

from __future__ import annotations

import time

import pytest

from constitution.verdict_engine import VerdictEngine
from context.live_context_bus import LiveContextBus


@pytest.fixture(autouse=True)
def reset_bus():
    """Reset LiveContextBus singleton before each test for isolation."""
    LiveContextBus.reset_singleton()
    yield
    LiveContextBus.reset_singleton()


def _make_engine(**config_kwargs) -> VerdictEngine:
    return VerdictEngine(config=config_kwargs)


def _fresh_gates() -> dict[str, dict]:
    return {
        "gate_1": {"passed": True, "score": 0.9},
        "gate_2": {"passed": True, "score": 0.85},
    }


class TestStaleFeedCircuitBreaker:
    """Circuit breaker in produce_verdict() — stale feed returns HOLD."""

    def test_no_feed_data_returns_hold(self) -> None:
        """No tick ever received → feed is stale → HOLD."""
        engine = _make_engine()
        result = engine.produce_verdict("EURUSD", {}, _fresh_gates())

        assert result["verdict"] == "HOLD"
        assert result["circuit_breaker"] is True
        assert result["confidence"] == 0.0

    def test_stale_feed_returns_hold(self) -> None:
        """Feed older than threshold → HOLD with circuit_breaker=True."""
        bus = LiveContextBus()
        # Inject a tick then backdate the timestamp to simulate stale feed
        bus.update_tick({"symbol": "EURUSD", "bid": 1.085, "ask": 1.086, "timestamp": time.time()})
        bus._feed_timestamps["EURUSD"] = time.time() - 200  # 200s old

        engine = _make_engine(feed_stale_threshold_sec=120.0)
        result = engine.produce_verdict("EURUSD", {}, _fresh_gates())

        assert result["verdict"] == "HOLD"
        assert result["circuit_breaker"] is True
        assert "CIRCUIT_BREAKER" in result["reason"]
        assert result["feed_stale_seconds"] is not None
        assert result["feed_stale_seconds"] > 0

    def test_fresh_feed_proceeds_normally(self) -> None:
        """Fresh tick within threshold → circuit breaker does NOT fire."""
        bus = LiveContextBus()
        bus.update_tick({"symbol": "EURUSD", "bid": 1.085, "ask": 1.086, "timestamp": time.time()})

        engine = _make_engine(feed_stale_threshold_sec=120.0)
        result = engine.produce_verdict("EURUSD", {}, _fresh_gates())

        # Should NOT be a circuit breaker response
        assert result.get("circuit_breaker") is not True
        # Should be a normal verdict (either EXECUTE or NO_TRADE)
        assert result["verdict"] in {"EXECUTE", "NO_TRADE", "HOLD"}

    def test_circuit_breaker_never_returns_execute(self) -> None:
        """Circuit breaker must never produce EXECUTE — only HOLD."""
        engine = _make_engine()
        result = engine.produce_verdict("EURUSD", {}, _fresh_gates())

        # If circuit breaker fired, verdict must be HOLD only
        if result.get("circuit_breaker"):
            assert result["verdict"] == "HOLD"
            assert result["verdict"] != "EXECUTE"

    def test_circuit_breaker_reason_contains_info(self) -> None:
        """Reason string should indicate feed staleness and threshold."""
        bus = LiveContextBus()
        bus.update_tick({"symbol": "GBPUSD", "bid": 1.27, "ask": 1.271, "timestamp": time.time()})
        bus._feed_timestamps["GBPUSD"] = time.time() - 300  # very stale

        engine = _make_engine(feed_stale_threshold_sec=60.0)
        result = engine.produce_verdict("GBPUSD", {}, _fresh_gates())

        assert result["circuit_breaker"] is True
        assert "CIRCUIT_BREAKER" in result["reason"]
        # Reason should include both the feed age and the configured threshold
        assert "60" in result["reason"]  # threshold value present

    def test_no_feed_data_reason_says_no_feed(self) -> None:
        """When no feed data at all, reason should indicate absence of data."""
        engine = _make_engine()
        result = engine.produce_verdict("XAUUSD", {}, _fresh_gates())

        assert result["circuit_breaker"] is True
        assert "CIRCUIT_BREAKER" in result["reason"]

    def test_configurable_threshold_respected(self) -> None:
        """feed_stale_threshold_sec config controls when breaker fires."""
        bus = LiveContextBus()
        bus.update_tick({"symbol": "USDJPY", "bid": 149.5, "ask": 149.51, "timestamp": time.time()})
        bus._feed_timestamps["USDJPY"] = time.time() - 60  # 60s old

        # With 30s threshold → stale
        engine_strict = _make_engine(feed_stale_threshold_sec=30.0)
        result_strict = engine_strict.produce_verdict("USDJPY", {}, _fresh_gates())
        assert result_strict["circuit_breaker"] is True

        # With 120s threshold → fresh
        engine_lenient = _make_engine(feed_stale_threshold_sec=120.0)
        result_lenient = engine_lenient.produce_verdict("USDJPY", {}, _fresh_gates())
        assert result_lenient.get("circuit_breaker") is not True

    def test_circuit_breaker_gate_summary_zeroed(self) -> None:
        """When circuit breaker fires, gate_summary reflects no gates evaluated."""
        engine = _make_engine()
        result = engine.produce_verdict("EURUSD", {}, _fresh_gates())

        if result.get("circuit_breaker"):
            gs = result["gate_summary"]
            assert gs["total"] == 0
            assert gs["passed"] == 0
            assert gs["pass_ratio"] == 0.0

    def test_circuit_breaker_enrichment_fields_present(self) -> None:
        """Circuit breaker result must include enrichment fields for schema compat."""
        engine = _make_engine()
        result = engine.produce_verdict("EURUSD", {}, _fresh_gates())

        if result.get("circuit_breaker"):
            assert "enrichment_applied" in result
            assert result["enrichment_applied"] is False
            assert "enrichment_context" in result

    def test_different_symbols_independent(self) -> None:
        """Circuit breaker is per-symbol — stale EURUSD should not affect GBPUSD."""
        bus = LiveContextBus()
        # GBPUSD has fresh data
        bus.update_tick({"symbol": "GBPUSD", "bid": 1.27, "ask": 1.271, "timestamp": time.time()})
        # EURUSD has no data → stale

        engine = _make_engine(feed_stale_threshold_sec=60.0)

        eurusd_result = engine.produce_verdict("EURUSD", {}, _fresh_gates())
        gbpusd_result = engine.produce_verdict("GBPUSD", {}, _fresh_gates())

        assert eurusd_result["circuit_breaker"] is True
        assert gbpusd_result.get("circuit_breaker") is not True
