"""
Tests for LiveContextBus inference state layer.

The inference layer holds abstract state that TUYUL reasons with:
  regime_state, volatility_regime, session_state,
  liquidity_map, news_pressure_vector, signal_stack.

These are ephemeral beliefs derived by analysis layers — NOT raw data.
"""

import threading

import pytest

from context.live_context_bus import LiveContextBus


@pytest.fixture(autouse=True)
def reset_bus_fixture():
    """Reset singleton state before each test."""
    bus = LiveContextBus()
    bus.reset_state()
    yield
    bus.reset_state()


class TestInferenceStateLifecycle:
    """Verify inference state is ephemeral and refreshable."""

    def test_initial_state_empty(self) -> None:
        bus = LiveContextBus()
        snap = bus.inference_snapshot()
        assert snap["regime_state"] == {}
        assert snap["volatility_regime"] == "NORMAL"
        assert snap["session_state"] == {}
        assert snap["liquidity_map"] == {}
        assert snap["news_pressure_vector"] == {}
        assert snap["signal_stack"] == []

    def test_reset_clears_inference(self) -> None:
        bus = LiveContextBus()
        bus.update_macro_state({"regime_state": 2, "vix_level": 30.0})
        bus.update_session_state({"session": "US_OVERLAP"})
        bus.reset_state()

        snap = bus.inference_snapshot()
        assert snap["regime_state"] == {}
        assert snap["session_state"] == {}


class TestMacroState:
    """Macro regime writes and reads."""

    def test_update_and_get(self) -> None:
        bus = LiveContextBus()
        state = {
            "vix_level": 22.5,
            "vix_regime": "HIGH",
            "regime_state": 2,
            "volatility_multiplier": 1.3,
            "risk_multiplier": 0.3,
        }
        bus.update_macro_state(state)

        got = bus.get_macro_state()
        assert got["vix_level"] == 22.5
        assert got["regime_state"] == 2

    def test_volatility_regime_derived_from_regime_state(self) -> None:
        bus = LiveContextBus()
        bus.update_macro_state({"regime_state": 0})
        assert bus.get_volatility_regime() == "LOW"

        bus.update_macro_state({"regime_state": 1})
        assert bus.get_volatility_regime() == "NORMAL"

        bus.update_macro_state({"regime_state": 2})
        assert bus.get_volatility_regime() == "HIGH"

    def test_get_returns_copy(self) -> None:
        bus = LiveContextBus()
        bus.update_macro_state({"vix_level": 15.0})
        got = bus.get_macro_state()
        got["vix_level"] = 999.0
        assert bus.get_macro_state()["vix_level"] == 15.0

    def test_macro_in_snapshot(self) -> None:
        bus = LiveContextBus()
        bus.update_macro_state({"vix_level": 18.0, "regime_state": 1})
        snap = bus.snapshot()
        assert snap["macro"]["vix_level"] == 18.0
        assert snap["inference"]["regime_state"]["regime_state"] == 1


class TestSessionState:
    """Session window state."""

    def test_update_and_get(self) -> None:
        bus = LiveContextBus()
        bus.update_session_state({
            "session": "LONDON_OPEN",
            "session_multiplier": 1.2,
            "is_overlap": False,
        })
        got = bus.get_session_state()
        assert got["session"] == "LONDON_OPEN"
        assert got["session_multiplier"] == 1.2


class TestLiquidityMap:
    """Liquidity zone abstractions."""

    def test_update_and_get(self) -> None:
        bus = LiveContextBus()
        bus.update_liquidity_map({
            "zones": [{"level": 1.0850, "strength": 0.9}],
            "nearest_zone": 1.0850,
        })
        got = bus.get_liquidity_map()
        assert len(got["zones"]) == 1
        assert got["nearest_zone"] == 1.0850


class TestNewsPressure:
    """News pressure vector."""

    def test_update_and_get(self) -> None:
        bus = LiveContextBus()
        bus.update_news_pressure({
            "pressure_score": 0.7,
            "locked_symbols": ["EURUSD"],
            "high_impact_pending": True,
        })
        got = bus.get_news_pressure()
        assert got["pressure_score"] == 0.7
        assert "EURUSD" in got["locked_symbols"]


class TestNews:
    """Raw news events."""

    def test_update_and_get(self) -> None:
        bus = LiveContextBus()
        bus.update_news({
            "events": [{"event": "NFP", "impact": "high"}],
            "source": "finnhub",
        })
        got = bus.get_news()
        assert got is not None
        assert got["source"] == "finnhub"

    def test_empty_returns_none(self) -> None:
        bus = LiveContextBus()
        assert bus.get_news() is None


class TestSignalStack:
    """Ephemeral signal candidate stack."""

    def test_push_and_get(self) -> None:
        bus = LiveContextBus()
        bus.push_signal({"symbol": "EURUSD", "direction": "BUY", "score": 24})
        bus.push_signal({"symbol": "GBPUSD", "direction": "SELL", "score": 18})

        stack = bus.get_signal_stack()
        assert len(stack) == 2
        assert stack[0]["symbol"] == "EURUSD"
        assert stack[1]["symbol"] == "GBPUSD"

    def test_stack_overflow_protection(self) -> None:
        bus = LiveContextBus()
        for i in range(60):
            bus.push_signal({"id": i})
        stack = bus.get_signal_stack()
        assert len(stack) == 50
        # Oldest dropped, latest kept
        assert stack[0]["id"] == 10
        assert stack[-1]["id"] == 59

    def test_clear(self) -> None:
        bus = LiveContextBus()
        bus.push_signal({"symbol": "EURUSD"})
        bus.clear_signal_stack()
        assert bus.get_signal_stack() == []


class TestInferenceSnapshot:
    """Unified inference state snapshot."""

    def test_full_snapshot(self) -> None:
        bus = LiveContextBus()
        bus.update_macro_state({"regime_state": 1, "vix_level": 16.0})
        bus.update_session_state({"session": "LONDON_OPEN"})
        bus.update_liquidity_map({"nearest_zone": 1.0850})
        bus.update_news_pressure({"pressure_score": 0.3})
        bus.push_signal({"symbol": "EURUSD"})

        snap = bus.inference_snapshot()
        assert snap["regime_state"]["regime_state"] == 1
        assert snap["volatility_regime"] == "NORMAL"
        assert snap["session_state"]["session"] == "LONDON_OPEN"
        assert snap["liquidity_map"]["nearest_zone"] == 1.0850
        assert snap["news_pressure_vector"]["pressure_score"] == 0.3
        assert len(snap["signal_stack"]) == 1
        assert snap["inference_ts"] > 0

    def test_snapshot_is_copy(self) -> None:
        bus = LiveContextBus()
        bus.update_macro_state({"vix_level": 15.0})
        snap = bus.inference_snapshot()
        snap["regime_state"]["vix_level"] = 999.0
        assert bus.inference_snapshot()["regime_state"]["vix_level"] == 15.0


class TestInferenceThreadSafety:
    """Concurrent inference state access."""

    def test_concurrent_writes(self) -> None:
        bus = LiveContextBus()

        def write_regime(thread_id: int):
            for _ in range(100):
                bus.update_macro_state({"regime_state": thread_id % 3})

        def write_session(thread_id: int):
            for _ in range(100):
                bus.update_session_state({"session": f"S{thread_id}"})

        threads = (
            [threading.Thread(target=write_regime, args=(i,)) for i in range(5)]
            + [threading.Thread(target=write_session, args=(i,)) for i in range(5)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No crash, state is consistent
        snap = bus.inference_snapshot()
        assert "regime_state" in snap
        assert "session_state" in snap


class TestGetCandle:
    """Convenience get_candle method."""

    def test_returns_latest(self) -> None:
        bus = LiveContextBus()
        bus.update_candle({"symbol": "EURUSD", "timeframe": "H1", "close": 1.085})
        bus.update_candle({"symbol": "EURUSD", "timeframe": "H1", "close": 1.086})
        c = bus.get_candle("EURUSD", "H1")
        assert c is not None
        assert c["close"] == 1.086

    def test_returns_none_when_empty(self) -> None:
        bus = LiveContextBus()
        assert bus.get_candle("UNKNOWN", "H1") is None
