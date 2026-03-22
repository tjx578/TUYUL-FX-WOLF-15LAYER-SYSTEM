"""
Tests for GAP #6 fix: warmup gate in pipeline.

Validates:
  1. LiveContextBus.check_warmup() returns correct ready/not-ready
  2. WolfConstitutionalPipeline.execute() blocks on insufficient warmup
  3. Warmup gate is bypassed in safe_mode
"""

from __future__ import annotations

from unittest.mock import MagicMock

from context.live_context_bus import LiveContextBus

# Default minimum bar requirements used across tests
_DEFAULT_MIN_BARS = {"M15": 20, "H1": 20, "H4": 10, "D1": 5}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_context_bus() -> LiveContextBus:
    """Reset the LiveContextBus singleton and return a fresh instance."""
    LiveContextBus._instance = None
    return LiveContextBus()


def _fill_candles(bus: LiveContextBus, symbol: str, tf: str, count: int) -> None:
    """Push `count` fake candles into the context bus history."""
    for i in range(count):
        candle = {
            "symbol": symbol,
            "timeframe": tf,
            "open": 1.0 + i * 0.0001,
            "high": 1.0 + i * 0.0001 + 0.0005,
            "low": 1.0 + i * 0.0001 - 0.0005,
            "close": 1.0 + (i + 1) * 0.0001,
            "volume": 100,
            "timestamp": 1700000000 + i * 900,  # 15-min intervals
        }
        bus.update_candle(candle)


# ---------------------------------------------------------------------------
# LiveContextBus.check_warmup()
# ---------------------------------------------------------------------------


class TestCheckWarmup:
    def setup_method(self):
        self.bus = _reset_context_bus()

    def teardown_method(self):
        LiveContextBus._instance = None

    def test_no_data_is_not_ready(self):
        result = self.bus.check_warmup("EURUSD", _DEFAULT_MIN_BARS)
        assert result["ready"] is False
        assert all(v == 0 for v in result["bars"].values())
        assert len(result["missing"]) > 0

    def test_partial_data_is_not_ready(self):
        _fill_candles(self.bus, "EURUSD", "M15", 25)
        _fill_candles(self.bus, "EURUSD", "H1", 25)
        # H4 and D1 still empty
        result = self.bus.check_warmup("EURUSD", _DEFAULT_MIN_BARS)
        assert result["ready"] is False
        assert "H4" in result["missing"]
        assert "D1" in result["missing"]

    def test_sufficient_data_is_ready(self):
        _fill_candles(self.bus, "EURUSD", "M15", 20)
        _fill_candles(self.bus, "EURUSD", "H1", 20)
        _fill_candles(self.bus, "EURUSD", "H4", 10)
        _fill_candles(self.bus, "EURUSD", "D1", 5)
        result = self.bus.check_warmup("EURUSD", _DEFAULT_MIN_BARS)
        assert result["ready"] is True
        assert result["missing"] == {}

    def test_custom_min_bars(self):
        _fill_candles(self.bus, "EURUSD", "M15", 5)
        result = self.bus.check_warmup("EURUSD", min_bars={"M15": 5})
        assert result["ready"] is True

    def test_exact_threshold_is_ready(self):
        """Exactly meeting the threshold should count as ready."""
        _fill_candles(self.bus, "EURUSD", "M15", 20)
        _fill_candles(self.bus, "EURUSD", "H1", 20)
        _fill_candles(self.bus, "EURUSD", "H4", 10)
        _fill_candles(self.bus, "EURUSD", "D1", 5)
        result = self.bus.check_warmup("EURUSD", _DEFAULT_MIN_BARS)
        assert result["ready"] is True

    def test_missing_reports_shortfall(self):
        _fill_candles(self.bus, "EURUSD", "M15", 15)
        _fill_candles(self.bus, "EURUSD", "H1", 20)
        _fill_candles(self.bus, "EURUSD", "H4", 10)
        _fill_candles(self.bus, "EURUSD", "D1", 5)
        result = self.bus.check_warmup("EURUSD", _DEFAULT_MIN_BARS)
        assert result["ready"] is False
        assert result["missing"] == {"M15": 5}

    def test_different_symbols_independent(self):
        _fill_candles(self.bus, "EURUSD", "M15", 30)
        _fill_candles(self.bus, "EURUSD", "H1", 30)
        _fill_candles(self.bus, "EURUSD", "H4", 15)
        _fill_candles(self.bus, "EURUSD", "D1", 10)
        _fill_candles(self.bus, "GBPJPY", "M15", 5)

        eur_result = self.bus.check_warmup("EURUSD", _DEFAULT_MIN_BARS)
        gbp_result = self.bus.check_warmup("GBPJPY", _DEFAULT_MIN_BARS)

        assert eur_result["ready"] is True
        assert gbp_result["ready"] is False


# ---------------------------------------------------------------------------
# Pipeline warmup gate
# ---------------------------------------------------------------------------


class TestPipelineWarmupGate:
    """Test that the pipeline rejects analysis when warmup is insufficient."""

    def _make_pipeline_with_warmup(self, warmup_result: dict):
        """Create a pipeline with a mocked context bus check_warmup."""
        from pipeline.wolf_constitutional_pipeline import (  # noqa: PLC0415
            WolfConstitutionalPipeline,
        )

        pipe = WolfConstitutionalPipeline()
        mock_bus = MagicMock()
        mock_bus.check_warmup.return_value = warmup_result
        pipe._context_bus = mock_bus
        pipe._ensure_analyzers = MagicMock()  # avoid real layer imports
        return pipe

    def test_insufficient_warmup_returns_early_exit(self):
        pipe = self._make_pipeline_with_warmup(
            {
                "ready": False,
                "bars": {"M15": 5, "H1": 3, "H4": 0, "D1": 0},
                "required": {"M15": 20, "H1": 20, "H4": 10, "D1": 5},
                "missing": {"M15": 15, "H1": 17, "H4": 10, "D1": 5},
            }
        )

        result = pipe.execute("EURUSD")

        assert any("WARMUP_INSUFFICIENT" in e for e in result["errors"])
        assert result["l12_verdict"]["verdict"] == "HOLD"
        # Pipeline should not have attempted any layer analysis
        pipe._context_bus.check_warmup.assert_called_once()  # pyright: ignore[reportAttributeAccessIssue]

    def test_sufficient_warmup_proceeds_to_analysis(self):
        """When warmup is OK, the pipeline should proceed past the gate."""
        from pipeline.wolf_constitutional_pipeline import (  # noqa: PLC0415
            WolfConstitutionalPipeline,
        )

        pipe = WolfConstitutionalPipeline()
        mock_bus = MagicMock()
        mock_bus.check_warmup.return_value = {
            "ready": True,
            "bars": {"M15": 25, "H1": 25, "H4": 15, "D1": 10},
            "required": {"M15": 20, "H1": 20, "H4": 10, "D1": 5},
            "missing": {},
        }
        pipe._context_bus = mock_bus

        # Patch _ensure_analyzers to avoid loading real layer modules
        # and mock L1 to return invalid (so it hits the first early exit after warmup)
        pipe._l1 = MagicMock()
        pipe._l1.analyze.return_value = {"valid": False}
        pipe._ensure_analyzers = MagicMock()

        result = pipe.execute("EURUSD")

        # Should have passed warmup and hit L1_CONTEXT_INVALID instead
        assert "WARMUP_INSUFFICIENT" not in result["errors"]
        assert "L1_CONTEXT_INVALID" in result["errors"]

    def test_safe_mode_bypasses_warmup(self):
        """safe_mode=True should skip the warmup check entirely."""
        pipe = self._make_pipeline_with_warmup(
            {
                "ready": False,
                "bars": {"M15": 0, "H1": 0, "H4": 0, "D1": 0},
                "required": {"M15": 20, "H1": 20, "H4": 10, "D1": 5},
                "missing": {"M15": 20, "H1": 20, "H4": 10, "D1": 5},
            }
        )

        # Patch _ensure_analyzers and mock L1
        pipe._l1 = MagicMock()
        pipe._l1.analyze.return_value = {"valid": False}
        pipe._ensure_analyzers = MagicMock()

        result = pipe.execute("EURUSD", system_metrics={"safe_mode": True})

        # Warmup check should NOT have been called
        pipe._context_bus.check_warmup.assert_not_called()  # pyright: ignore[reportAttributeAccessIssue]
        # Should have proceeded past warmup to L1
        assert "WARMUP_INSUFFICIENT" not in result["errors"]
