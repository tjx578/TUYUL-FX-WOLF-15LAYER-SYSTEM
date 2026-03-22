"""Tests for LiveContextBus.check_warmup() — schema contract.

Ensures the bus always returns the stable schema expected by the pipeline
and existing tests (bars / required / missing / details).
"""

from __future__ import annotations

from context.live_context_bus import LiveContextBus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_bus() -> LiveContextBus:
    """Return a LiveContextBus with a clean internal state.

    We call reset_state() so tests are isolated without having to destroy
    the singleton (which other modules may hold).
    """
    bus = LiveContextBus()
    bus.reset_state()  # <-- added parentheses
    return bus


def _fill(bus: LiveContextBus, symbol: str, tf: str, count: int) -> None:
    candles = [{"open": 1.0, "close": 1.0, "high": 1.0, "low": 1.0} for _ in range(count)]
    bus.set_candle_history(symbol, tf, candles)


# ---------------------------------------------------------------------------
# Schema shape tests
# ---------------------------------------------------------------------------


class TestCheckWarmupSchema:
    """check_warmup must always return all top-level keys."""

    def test_keys_present_when_ready(self):
        bus = _fresh_bus()
        _fill(bus, "EURUSD", "H4", 200)
        result = bus.check_warmup("EURUSD", {"H4": 200})

        assert set(result.keys()) == {"ready", "bars", "required", "missing", "details"}

    def test_keys_present_when_not_ready(self):
        bus = _fresh_bus()
        result = bus.check_warmup("EURUSD", {"H4": 200})

        assert set(result.keys()) == {"ready", "bars", "required", "missing", "details"}

    def test_keys_present_empty_min_bars(self):
        bus = _fresh_bus()
        result = bus.check_warmup("EURUSD", {})

        assert set(result.keys()) == {"ready", "bars", "required", "missing", "details"}
        assert result["ready"] is True
        assert result["bars"] == {}
        assert result["required"] == {}
        assert result["missing"] == {}
        assert result["details"] == {}


# ---------------------------------------------------------------------------
# Ready / not-ready logic
# ---------------------------------------------------------------------------


class TestCheckWarmupReadiness:
    def test_ready_when_all_tfs_met(self):
        bus = _fresh_bus()
        _fill(bus, "GBPUSD", "H4", 200)
        _fill(bus, "GBPUSD", "H1", 500)
        result = bus.check_warmup("GBPUSD", {"H4": 200, "H1": 500})

        assert result["ready"] is True
        assert result["missing"] == {}

    def test_not_ready_when_one_tf_short(self):
        bus = _fresh_bus()
        _fill(bus, "GBPUSD", "H4", 200)
        _fill(bus, "GBPUSD", "H1", 300)  # needs 500
        result = bus.check_warmup("GBPUSD", {"H4": 200, "H1": 500})

        assert result["ready"] is False
        assert "H1" in result["missing"]
        assert result["missing"]["H1"] == 200

    def test_not_ready_when_no_candles(self):
        bus = _fresh_bus()
        result = bus.check_warmup("USDJPY", {"H4": 100})

        assert result["ready"] is False
        assert result["bars"]["H4"] == 0
        assert result["missing"]["H4"] == 100

    def test_ready_when_bars_exceed_required(self):
        """More bars than required should still be ready."""
        bus = _fresh_bus()
        _fill(bus, "EURUSD", "M15", 999)
        result = bus.check_warmup("EURUSD", {"M15": 500})

        assert result["ready"] is True
        assert result["bars"]["M15"] == 999
        assert result["missing"] == {}


# ---------------------------------------------------------------------------
# bars / required / missing / details values
# ---------------------------------------------------------------------------


class TestCheckWarmupValues:
    def test_bars_map_reflects_actual_count(self):
        bus = _fresh_bus()
        _fill(bus, "EURUSD", "H4", 123)
        result = bus.check_warmup("EURUSD", {"H4": 200})

        assert result["bars"]["H4"] == 123
        assert result["required"]["H4"] == 200
        assert result["missing"]["H4"] == 77

    def test_details_mirror_bars_required_missing(self):
        bus = _fresh_bus()
        _fill(bus, "EURUSD", "H4", 123)
        result = bus.check_warmup("EURUSD", {"H4": 200})

        d = result["details"]["H4"]
        assert d["have"] == result["bars"]["H4"]
        assert d["need"] == result["required"]["H4"]
        assert d["missing"] == result["missing"]["H4"]

    def test_missing_only_contains_short_tfs(self):
        bus = _fresh_bus()
        _fill(bus, "EURUSD", "H4", 200)  # met
        _fill(bus, "EURUSD", "H1", 100)  # short by 400
        result = bus.check_warmup("EURUSD", {"H4": 200, "H1": 500})

        assert "H4" not in result["missing"]
        assert result["missing"]["H1"] == 400

    def test_multi_tf_all_short(self):
        bus = _fresh_bus()
        _fill(bus, "XAUUSD", "H4", 10)
        _fill(bus, "XAUUSD", "M15", 20)
        result = bus.check_warmup("XAUUSD", {"H4": 200, "M15": 1000})

        assert result["ready"] is False
        assert result["missing"]["H4"] == 190
        assert result["missing"]["M15"] == 980


# ---------------------------------------------------------------------------
# Backward-compat: 'details' key still present
# ---------------------------------------------------------------------------


class TestCheckWarmupDetailsBackwardCompat:
    def test_details_present_and_correct_when_ready(self):
        bus = _fresh_bus()
        _fill(bus, "EURUSD", "H4", 300)
        result = bus.check_warmup("EURUSD", {"H4": 200})

        assert "details" in result
        assert result["details"]["H4"]["have"] == 300
        assert result["details"]["H4"]["need"] == 200
        assert result["details"]["H4"]["missing"] == 0

    def test_details_present_when_not_ready(self):
        bus = _fresh_bus()
        result = bus.check_warmup("EURUSD", {"H4": 200})

        assert "details" in result
        assert result["details"]["H4"]["have"] == 0
        assert result["details"]["H4"]["missing"] == 200
