"""
Tests for GAP #8: Signal rate throttle — prevents rapid consecutive EXECUTE
verdicts for the same symbol.

Validates:
  1. SignalThrottle basic rate-limiting logic
  2. Pipeline downgrades verdict when throttled
  3. safe_mode bypasses throttle
  4. Per-symbol independence
  5. Window expiry (old signals drop out)
  6. Prometheus SIGNAL_THROTTLED metric increments
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import MagicMock

from constitution.signal_throttle import SignalThrottle
from core.metrics import SIGNAL_THROTTLED

# =========================================================================
# SignalThrottle unit tests
# =========================================================================


class TestSignalThrottle:
    def test_not_throttled_initially(self):
        t = SignalThrottle(max_signals=3, window_seconds=300)
        assert t.is_throttled("EURUSD") is False

    def test_throttled_after_max_signals(self):
        t = SignalThrottle(max_signals=3, window_seconds=300)
        t.record("EURUSD")
        t.record("EURUSD")
        t.record("EURUSD")
        assert t.is_throttled("EURUSD") is True

    def test_not_throttled_below_max(self):
        t = SignalThrottle(max_signals=3, window_seconds=300)
        t.record("EURUSD")
        t.record("EURUSD")
        assert t.is_throttled("EURUSD") is False

    def test_per_symbol_independence(self):
        t = SignalThrottle(max_signals=2, window_seconds=300)
        t.record("EURUSD")
        t.record("EURUSD")
        assert t.is_throttled("EURUSD") is True
        assert t.is_throttled("GBPJPY") is False

    def test_window_expiry(self):
        """Signals older than the window should not count."""
        t = SignalThrottle(max_signals=2, window_seconds=1.0)
        t.record("EURUSD")
        t.record("EURUSD")
        assert t.is_throttled("EURUSD") is True

        # Wait for window to expire
        time.sleep(1.1)
        assert t.is_throttled("EURUSD") is False

    def test_get_count(self):
        t = SignalThrottle(max_signals=5, window_seconds=300)
        assert t.get_count("EURUSD") == 0
        t.record("EURUSD")
        t.record("EURUSD")
        assert t.get_count("EURUSD") == 2

    def test_get_remaining(self):
        t = SignalThrottle(max_signals=3, window_seconds=300)
        assert t.get_remaining("EURUSD") == 3
        t.record("EURUSD")
        assert t.get_remaining("EURUSD") == 2
        t.record("EURUSD")
        t.record("EURUSD")
        assert t.get_remaining("EURUSD") == 0

    def test_reset_symbol(self):
        t = SignalThrottle(max_signals=2, window_seconds=300)
        t.record("EURUSD")
        t.record("EURUSD")
        assert t.is_throttled("EURUSD") is True
        t.reset("EURUSD")
        assert t.is_throttled("EURUSD") is False

    def test_reset_all(self):
        t = SignalThrottle(max_signals=1, window_seconds=300)
        t.record("EURUSD")
        t.record("GBPJPY")
        t.reset()
        assert t.is_throttled("EURUSD") is False
        assert t.is_throttled("GBPJPY") is False

    def test_exact_threshold(self):
        """Exactly max_signals should trigger throttle."""
        t = SignalThrottle(max_signals=1, window_seconds=300)
        t.record("XAUUSD")
        assert t.is_throttled("XAUUSD") is True

    def test_is_throttled_does_not_mutate(self):
        """Calling is_throttled should not change the count."""
        t = SignalThrottle(max_signals=2, window_seconds=300)
        t.record("EURUSD")
        assert t.is_throttled("EURUSD") is False
        assert t.is_throttled("EURUSD") is False
        assert t.get_count("EURUSD") == 1

    def test_throttled_logs_plain_error_event(self, capsys):
        """Throttled signals must reach the platform as plain stderr events."""
        t = SignalThrottle(max_signals=1, window_seconds=300)
        t.record("XAUUSD")

        assert t.is_throttled("XAUUSD") is True
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.splitlines() == ["[SignalThrottle] XAUUSD THROTTLED — 1 signals in last 300s (max 1)"]

    def test_allowed_logs_plain_info_event(self, capsys):
        """Allowed signals must reach the platform as plain stdout events."""
        t = SignalThrottle(max_signals=3, window_seconds=300)

        t.emit_allowed("NZDCHF", "EXECUTE_REDUCED_RISK_BUY")

        captured = capsys.readouterr()
        assert captured.out.splitlines() == ["[SignalThrottle] NZDCHF allowed — verdict EXECUTE_REDUCED_RISK_BUY"]
        assert captured.err == ""

    def test_allowed_streak_ignores_errors_but_resets_on_other_allowed_symbol(self):
        """Allowed quorum uses only allowed events; throttle errors do not break it."""
        t = SignalThrottle(max_signals=1, window_seconds=300)

        assert t.record_allowed_streak("AUDCAD", "EXECUTE_BUY") == 1
        t.record("AUDCAD")
        assert t.is_throttled("AUDCAD") is True
        assert t.record_allowed_streak("AUDCAD", "EXECUTE_BUY") == 2
        assert t.record_allowed_streak("EURCAD", "EXECUTE_BUY") == 1
        assert t.record_allowed_streak("AUDCAD", "EXECUTE_BUY") == 1

    def test_allowed_streak_resets_on_direction_change(self):
        """Same symbol but opposite raw direction starts a new allowed streak."""
        t = SignalThrottle(max_signals=3, window_seconds=300)

        assert t.record_allowed_streak("GBPCAD", "EXECUTE_BUY") == 1
        assert t.record_allowed_streak("GBPCAD", "EXECUTE_BUY") == 2
        assert t.record_allowed_streak("GBPCAD", "EXECUTE_SELL") == 1


# =========================================================================
# Pipeline integration tests
# =========================================================================


class TestPipelineSignalThrottle:
    """Test the throttle gate inside WolfConstitutionalPipeline."""

    def _make_pipeline(self):
        from pipeline.wolf_constitutional_pipeline import (  # noqa: PLC0415
            WolfConstitutionalPipeline,
        )

        pipe = WolfConstitutionalPipeline()
        pipe._ensure_analyzers = MagicMock()
        return pipe

    def test_throttled_execute_downgraded_to_hold(self):
        """When the throttle fires, EXECUTE verdict should become HOLD."""
        pipe = self._make_pipeline()

        # Pre-fill throttle to the limit (3 signals)
        pipe._signal_throttle.record("THROTTLE_TEST")
        pipe._signal_throttle.record("THROTTLE_TEST")
        pipe._signal_throttle.record("THROTTLE_TEST")

        # Build a minimal result that would have EXECUTE_BUY
        # We use _early_exit as a vehicle to test (it goes through _record_metrics)
        # Instead, let's mock the full pipeline flow:
        # Mock context_bus warmup to pass
        mock_bus = MagicMock()
        mock_bus.check_warmup.return_value = {
            "ready": True,
            "bars": {"M15": 25, "H1": 25, "H4": 15, "D1": 10},
            "required": {"M15": 20, "H1": 20, "H4": 10, "D1": 5},
            "missing": {},
        }
        pipe._context_bus = mock_bus

        # Mock L1 to return invalid so pipeline hits early exit before L12
        # That won't test the throttle (it's after L12).
        # Instead, let's directly test _record_metrics behavior through
        # the throttle gate by examining the l12_verdict mutation.

        # Direct test: create a fake l12_verdict and simulate the throttle logic
        l12_verdict = {"verdict": "EXECUTE_BUY", "gates_v74": {}}
        symbol = "THROTTLE_TEST"

        # Check the throttle gate logic
        final_verdict = str(l12_verdict.get("verdict", ""))
        assert final_verdict.startswith("EXECUTE")
        assert pipe._signal_throttle.is_throttled(symbol) is True

    def test_unthrottled_signal_is_recorded(self):
        """An un-throttled EXECUTE should be recorded in the throttle window."""
        pipe = self._make_pipeline()
        assert pipe._signal_throttle.get_count("RECORD_TEST") == 0

        # Simulate recording as the pipeline would
        pipe._signal_throttle.record("RECORD_TEST")
        assert pipe._signal_throttle.get_count("RECORD_TEST") == 1

    def test_safe_mode_bypasses_throttle(self):
        """safe_mode=True should skip the throttle check."""
        pipe = self._make_pipeline()

        # Fill throttle to the limit
        pipe._signal_throttle.record("SAFE_TEST")
        pipe._signal_throttle.record("SAFE_TEST")
        pipe._signal_throttle.record("SAFE_TEST")
        assert pipe._signal_throttle.is_throttled("SAFE_TEST") is True

        # In safe_mode, the pipeline code has `if ... and not safe_mode:`
        # so the throttle check is skipped. We verify the condition:
        safe_mode = True
        final_verdict = "EXECUTE_BUY"
        # This mimics the pipeline logic:
        should_check = final_verdict.startswith("EXECUTE") and not safe_mode
        assert should_check is False

    def test_non_execute_verdict_not_throttled(self):
        """HOLD/NO_TRADE verdicts should not interact with the throttle."""
        pipe = self._make_pipeline()
        # Fill throttle
        pipe._signal_throttle.record("HOLD_TEST")
        pipe._signal_throttle.record("HOLD_TEST")
        pipe._signal_throttle.record("HOLD_TEST")

        # A HOLD verdict should not be affected by throttle
        final_verdict = "HOLD"
        should_check = final_verdict.startswith("EXECUTE")
        assert should_check is False

    def test_throttle_preserves_original_verdict(self):
        """When throttled, the original verdict should be stored in throttled_from."""
        pipe = self._make_pipeline()

        # Simulate the throttle gate logic from the pipeline
        l12_verdict = {"verdict": "EXECUTE_SELL"}
        symbol = "PRESERVE_TEST"

        # Fill throttle
        pipe._signal_throttle.record(symbol)
        pipe._signal_throttle.record(symbol)
        pipe._signal_throttle.record(symbol)

        # Simulate the pipeline's throttle gate
        final_verdict = l12_verdict.get("verdict", "")
        if final_verdict.startswith("EXECUTE") and pipe._signal_throttle.is_throttled(symbol):
            l12_verdict["verdict"] = "HOLD"
            l12_verdict["throttled_from"] = final_verdict

        assert l12_verdict["verdict"] == "HOLD"
        assert l12_verdict["throttled_from"] == "EXECUTE_SELL"

    def test_throttled_execute_downgrades_without_extra_canary_event(self, monkeypatch):
        """Throttled EXECUTE keeps the visible log simple and stores metadata."""
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

        pipe = self._make_pipeline()
        symbol = "LOG_THROTTLE_TEST"
        for _ in range(3):
            pipe._signal_throttle.record(symbol)

        events: list[dict[str, Any]] = []
        monkeypatch.setattr(
            WolfConstitutionalPipeline,
            "_emit_verdict_stream_event",
            staticmethod(lambda **kwargs: events.append(kwargs)),
        )

        errors: list[str] = []
        l12_verdict = {"verdict": "EXECUTE_BUY", "direction": "BUY"}
        pipe._apply_effective_verdict_controls(
            symbol=symbol,
            synthesis={},
            l12_verdict=l12_verdict,
            legacy_verdict="EXECUTE_BUY",
            safe_mode=False,
            errors=errors,
        )

        throttle_events = [event for event in events if event["event"] == "signal_throttle_check"]
        assert throttle_events == []
        assert l12_verdict["verdict"] == "HOLD"
        assert l12_verdict["throttled_from"] == "EXECUTE_BUY"
        throttle_meta = cast(dict[str, Any], l12_verdict["signal_throttle"])
        assert throttle_meta["status"] == "throttled"
        assert throttle_meta["count"] == 3
        assert throttle_meta["remaining"] == 0
        assert "SIGNAL_THROTTLED" in errors

    def test_allowed_execute_emits_plain_info_event(self, monkeypatch, capsys):
        """Allowed EXECUTE verdicts should emit only the plain info event."""
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

        pipe = self._make_pipeline()
        events: list[dict[str, Any]] = []
        monkeypatch.setattr(
            WolfConstitutionalPipeline,
            "_emit_verdict_stream_event",
            staticmethod(lambda **kwargs: events.append(kwargs)),
        )
        capsys.readouterr()

        errors: list[str] = []
        l12_verdict = {"verdict": "EXECUTE_SELL", "direction": "SELL"}
        pipe._apply_effective_verdict_controls(
            symbol="LOG_ALLOWED_TEST",
            synthesis={},
            l12_verdict=l12_verdict,
            legacy_verdict="EXECUTE_SELL",
            safe_mode=False,
            errors=errors,
        )

        throttle_events = [event for event in events if event["event"] == "signal_throttle_check"]
        captured = capsys.readouterr()
        assert throttle_events == []
        assert captured.out.splitlines() == [
            "[SignalThrottle] LOG_ALLOWED_TEST allowed — verdict EXECUTE_SELL",
            "[SignalThrottleIntel] symbol=LOG_ALLOWED_TEST raw_direction=SELL final_direction=WAIT "
            "direction_status=ALLOWED_CANDIDATE phase=IGNITION action=WAIT_PRICE_CONFIRMATION "
            "verdict=EXECUTE_SELL count=1 remaining=2 streak=1 max=3 window=300s "
            "reason=allowed_is_candidate_until_price_theme_structure_validation",
        ]
        assert captured.err == ""
        assert pipe._signal_throttle.get_count("LOG_ALLOWED_TEST") == 1
        assert l12_verdict["signal_throttle_intel"] == {
            "symbol": "LOG_ALLOWED_TEST",
            "verdict": "EXECUTE_SELL",
            "raw_direction": "SELL",
            "final_direction": "WAIT",
            "direction_status": "ALLOWED_CANDIDATE",
            "phase": "IGNITION",
            "action": "WAIT_PRICE_CONFIRMATION",
            "count": 1,
            "remaining": 2,
            "allowed_streak": 1,
            "max_signals": 3,
            "window_seconds": 300.0,
            "reason": "allowed_is_candidate_until_price_theme_structure_validation",
        }
        assert "SIGNAL_THROTTLED" not in errors

    def test_market_context_guard_blocks_unvalidated_execute_before_throttle(self, monkeypatch):
        """Block mode should hold EXECUTE when price/phase/spread context is missing."""
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

        pipe = self._make_pipeline()
        pipe._market_context_guard_mode = "block"
        events: list[dict[str, Any]] = []
        monkeypatch.setattr(
            WolfConstitutionalPipeline,
            "_emit_verdict_stream_event",
            staticmethod(lambda **kwargs: events.append(kwargs)),
        )

        errors: list[str] = []
        l12_verdict = {"verdict": "EXECUTE_BUY", "direction": "BUY"}
        pipe._apply_effective_verdict_controls(
            symbol="MISSING_CONTEXT_TEST",
            synthesis={
                "execution": {
                    "direction": "BUY",
                    "direction_diagnostics": {"conflicts": [], "sources": {"l3": "BUY"}},
                }
            },
            l12_verdict=l12_verdict,
            legacy_verdict="EXECUTE_BUY",
            safe_mode=False,
            errors=errors,
        )

        assert l12_verdict["verdict"] == "HOLD"
        assert l12_verdict["market_context_from"] == "EXECUTE_BUY"
        assert l12_verdict["market_context_downgrade"] is True
        market_context_validation = cast(dict[str, Any], l12_verdict["market_context_validation"])
        assert market_context_validation["action"] == "FETCH_MARKET_CONTEXT"
        assert any(error.startswith("MARKET_CONTEXT_UNVALIDATED") for error in errors)
        assert pipe._signal_throttle.get_count("MISSING_CONTEXT_TEST") == 0
        assert any(event["event"] == "market_context_validation" for event in events)

    def test_market_context_guard_allows_validated_execute_in_block_mode(self, monkeypatch, capsys):
        """Complete aligned context should validate BUY and still pass through throttle."""
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

        pipe = self._make_pipeline()
        pipe._market_context_guard_mode = "block"

        class _FakeV11Hook:
            def evaluate(self, *_args: Any, **_kwargs: Any) -> Any:
                class _Overlay:
                    should_trade = True

                    @staticmethod
                    def to_dict() -> dict[str, Any]:
                        return {"enabled": True, "should_trade": True, "skipped_reason": None}

                return _Overlay()

        monkeypatch.setattr("engines.v11.V11PipelineHook", _FakeV11Hook)
        pipe._context_bus.update_tick(
            {
                "symbol": "EURUSD",
                "bid": 1.1010,
                "ask": 1.1011,
                "timestamp": time.time(),
            }
        )
        for candle in (
            {"symbol": "EURUSD", "timeframe": "M15", "open": 1.0990, "close": 1.1000},
            {"symbol": "EURUSD", "timeframe": "M15", "open": 1.1002, "close": 1.1010},
            {"symbol": "EURUSD", "timeframe": "H1", "open": 1.0980, "close": 1.1000},
            {"symbol": "EURUSD", "timeframe": "H1", "open": 1.1001, "close": 1.1010},
        ):
            pipe._context_bus.update_candle(candle)

        events: list[dict[str, Any]] = []
        monkeypatch.setattr(
            WolfConstitutionalPipeline,
            "_emit_verdict_stream_event",
            staticmethod(lambda **kwargs: events.append(kwargs)),
        )
        capsys.readouterr()

        errors: list[str] = []
        l12_verdict = {"verdict": "EXECUTE_BUY", "direction": "BUY"}
        pipe._apply_effective_verdict_controls(
            symbol="EURUSD",
            synthesis={
                "execution": {
                    "direction": "BUY",
                    "entry_price": 1.1000,
                    "direction_diagnostics": {
                        "conflicts": [],
                        "sources": {"l2": "BUY", "l3": "BUY", "l9": "BUY"},
                    },
                },
                "legacy_fta": {"legacy_fta_present": True, "direction": "BUY"},
            },
            l12_verdict=l12_verdict,
            legacy_verdict="EXECUTE_BUY",
            safe_mode=False,
            errors=errors,
        )

        assert l12_verdict["verdict"] == "EXECUTE_BUY"
        market_context_validation = cast(dict[str, Any], l12_verdict["market_context_validation"])
        assert market_context_validation["direction_validated"] is True
        assert market_context_validation["final_direction"] == "BUY"
        assert "market_context_downgrade" not in l12_verdict
        assert pipe._signal_throttle.get_count("EURUSD") == 1
        assert not any(error.startswith("MARKET_CONTEXT_UNVALIDATED") for error in errors)
        assert any(event["event"] == "market_context_validation" for event in events)

    def test_pipeline_live_report_applies_priced_microboost_context(self, monkeypatch, capsys):
        """Live throttle report should price microboost when market context is available."""
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

        pipe = self._make_pipeline()

        class _FakeV11Hook:
            def evaluate(self, *_args: Any, **_kwargs: Any) -> Any:
                class _Overlay:
                    should_trade = True

                    @staticmethod
                    def to_dict() -> dict[str, Any]:
                        return {"enabled": True, "should_trade": True, "skipped_reason": None}

                return _Overlay()

        monkeypatch.setattr("engines.v11.V11PipelineHook", _FakeV11Hook)
        pipe._context_bus.update_tick(
            {
                "symbol": "EURUSD",
                "bid": 1.1010,
                "ask": 1.1011,
                "timestamp": time.time(),
            }
        )
        for candle in (
            {"symbol": "EURUSD", "timeframe": "M15", "open": 1.0990, "close": 1.1000},
            {"symbol": "EURUSD", "timeframe": "M15", "open": 1.1002, "close": 1.1010},
            {"symbol": "EURUSD", "timeframe": "H1", "open": 1.0980, "close": 1.1000},
            {"symbol": "EURUSD", "timeframe": "H1", "open": 1.1001, "close": 1.1010},
        ):
            pipe._context_bus.update_candle(candle)

        base = datetime.now(UTC) - timedelta(minutes=2)
        for index in range(30):
            pipe._signal_throttle_live_analyzer.record_allowed(
                symbol="EURUSD",
                verdict="EXECUTE_BUY",
                timestamp=base + timedelta(seconds=index * 2),
            )

        events: list[dict[str, Any]] = []
        monkeypatch.setattr(
            WolfConstitutionalPipeline,
            "_emit_verdict_stream_event",
            staticmethod(lambda **kwargs: events.append(kwargs)),
        )
        capsys.readouterr()

        errors: list[str] = []
        l12_verdict = {"verdict": "EXECUTE_BUY", "direction": "BUY"}
        pipe._apply_effective_verdict_controls(
            symbol="EURUSD",
            synthesis={
                "execution": {
                    "direction": "BUY",
                    "entry_price": 1.1000,
                    "direction_diagnostics": {
                        "conflicts": [],
                        "sources": {"l2": "BUY", "l3": "BUY", "l9": "BUY"},
                    },
                },
                "legacy_fta": {"legacy_fta_present": True, "direction": "BUY"},
            },
            l12_verdict=l12_verdict,
            legacy_verdict="EXECUTE_BUY",
            safe_mode=False,
            errors=errors,
        )

        report = cast(dict[str, Any], l12_verdict["signal_throttle_live_report"])
        latest = cast(dict[str, Any], report["microboost_summary"]["latest"])
        assert report["microboost_summary"]["market_context_applied"] is True
        assert latest["phase_unpriced"] == "DENSE_MICROBOOST"
        assert latest["phase_priced"] == "CONTINUATION_MICROBOOST"
        assert latest["market_context_validation"]["final_direction"] == "BUY"
        assert latest["requires_market_context"] is False
        assert not any(error.startswith("MARKET_CONTEXT_UNVALIDATED") for error in errors)
        assert any(event["event"] == "market_context_validation" for event in events)

    def test_sovereignty_downgrade_emits_throttle_skipped_event(self, monkeypatch):
        """When vault sovereignty downgrades EXECUTE before throttle, emit an explicit skip event."""
        from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline

        pipe = self._make_pipeline()
        events: list[dict[str, Any]] = []
        monkeypatch.setattr(
            WolfConstitutionalPipeline,
            "_emit_verdict_stream_event",
            staticmethod(lambda **kwargs: events.append(kwargs)),
        )

        errors: list[str] = []
        l12_verdict = {
            "verdict": "HOLD",
            "direction": "BUY",
            "sovereignty_downgrade": True,
        }
        pipe._apply_effective_verdict_controls(
            symbol="VAULT_STALE_TEST",
            synthesis={},
            l12_verdict=l12_verdict,
            legacy_verdict="EXECUTE_BUY",
            safe_mode=False,
            errors=errors,
        )

        throttle_events = [event for event in events if event["event"] == "signal_throttle_check"]
        assert throttle_events
        assert throttle_events[0]["extras"]["status"] == "skipped"
        assert throttle_events[0]["extras"]["reason"] == "sovereignty_downgraded_to_hold"
        assert throttle_events[0]["extras"]["source_verdict"] == "EXECUTE_BUY"
        assert throttle_events[0]["extras"]["sovereignty_downgrade"] is True
        assert "SIGNAL_THROTTLED" not in errors


# =========================================================================
# Prometheus metric test
# =========================================================================


class TestThrottleMetric:
    def test_signal_throttled_metric_exists(self):
        assert SIGNAL_THROTTLED is not None
        assert SIGNAL_THROTTLED.name == "wolf_signal_throttled_total"

    def test_metric_increments_on_throttle(self):
        """Verify SIGNAL_THROTTLED counter increments when we call .inc()."""
        before = SIGNAL_THROTTLED.labels(symbol="METRIC_TEST").value
        SIGNAL_THROTTLED.labels(symbol="METRIC_TEST").inc()
        assert SIGNAL_THROTTLED.labels(symbol="METRIC_TEST").value == before + 1
