"""Tests for DataQualityGate — candle gap validation & degradation signaling."""

from __future__ import annotations

import time

import pytest

from analysis.data_quality_gate import DataQualityConfig, DataQualityGate


def _make_candle(has_gap: bool = False, tick_count: int = 10) -> dict:
    return {
        "symbol": "EURUSD",
        "timeframe": "M15",
        "open": 1.0850,
        "high": 1.0860,
        "low": 1.0840,
        "close": 1.0855,
        "volume": tick_count,
        "has_gap": has_gap,
        "tick_count": tick_count,
    }


class TestDataQualityGate:
    """Tests for candle data quality assessment."""

    def test_healthy_candles_no_degradation(self) -> None:
        gate = DataQualityGate()
        candles = [_make_candle() for _ in range(50)]
        report = gate.assess("EURUSD", "M15", candles, last_update_ts=time.time())
        assert report.degraded is False
        assert report.confidence_penalty == 0.0
        assert report.freshness_state == "fresh"
        assert report.gap_candles == 0
        assert report.gap_ratio == 0.0

    def test_high_gap_ratio_triggers_degradation(self) -> None:
        gate = DataQualityGate(DataQualityConfig(max_gap_ratio=0.10))
        candles = [_make_candle(has_gap=(i % 5 == 0)) for i in range(50)]
        report = gate.assess("EURUSD", "M15", candles, last_update_ts=time.time())
        assert report.degraded is True
        assert report.gap_ratio == pytest.approx(0.20, abs=0.01)
        assert report.confidence_penalty > 0

    def test_low_gap_ratio_no_degradation(self) -> None:
        gate = DataQualityGate(DataQualityConfig(max_gap_ratio=0.10))
        candles = [_make_candle(has_gap=(i == 0)) for i in range(50)]
        report = gate.assess("EURUSD", "M15", candles, last_update_ts=time.time())
        assert report.gap_ratio == pytest.approx(0.02, abs=0.01)
        assert report.degraded is False

    def test_low_tick_count_triggers_degradation(self) -> None:
        gate = DataQualityGate(DataQualityConfig(min_tick_count=5, max_low_tick_ratio=0.10))
        candles = [_make_candle(tick_count=2) for _ in range(50)]
        report = gate.assess("EURUSD", "M15", candles, last_update_ts=time.time())
        assert report.degraded is True
        assert report.low_tick_candles == 50
        assert "low_tick_candles" in report.reasons[0]

    def test_stale_data_triggers_degradation(self) -> None:
        gate = DataQualityGate(DataQualityConfig(stale_threshold_seconds=10.0, stale_candle_multiplier=0.0))
        candles = [_make_candle() for _ in range(50)]
        old_ts = time.time() - 60.0
        report = gate.assess("EURUSD", "M15", candles, last_update_ts=old_ts)
        assert report.degraded is True
        assert report.freshness_state == "stale_preserved"
        assert report.staleness_seconds > 50.0
        assert any("stale" in r for r in report.reasons)

    def test_h1_not_stale_within_two_candles(self) -> None:
        gate = DataQualityGate()
        candles = [_make_candle() for _ in range(50)]
        # H1 default stale threshold = max(300s, 3 * 3600s) = 10800s
        old_ts = time.time() - 3900.0
        report = gate.assess("EURUSD", "H1", candles, last_update_ts=old_ts)
        assert report.degraded is False
        assert not any("stale_data" in r for r in report.reasons)

    def test_h1_stale_after_two_candles(self) -> None:
        gate = DataQualityGate()
        candles = [_make_candle() for _ in range(50)]
        old_ts = time.time() - 12000.0
        report = gate.assess("EURUSD", "H1", candles, last_update_ts=old_ts)
        assert report.degraded is True
        assert any("stale_data" in r for r in report.reasons)

    def test_monthly_not_stale_for_short_age(self) -> None:
        gate = DataQualityGate()
        candles = [_make_candle() for _ in range(50)]
        # MN default stale threshold = 2 * 30 days
        old_ts = time.time() - (10 * 24 * 3600)
        report = gate.assess("EURUSD", "MN", candles, last_update_ts=old_ts)
        assert report.degraded is False
        assert not any("stale_data" in r for r in report.reasons)

    def test_empty_candles_max_penalty(self) -> None:
        gate = DataQualityGate()
        report = gate.assess("EURUSD", "M15", [])
        assert report.degraded is True
        assert report.freshness_state == "no_producer"
        assert report.confidence_penalty == DataQualityConfig().max_penalty
        assert "no_candles" in report.reasons

    def test_penalty_capped_at_max(self) -> None:
        cfg = DataQualityConfig(
            max_gap_ratio=0.01,
            max_low_tick_ratio=0.01,
            stale_threshold_seconds=1.0,
            max_penalty=0.25,
        )
        gate = DataQualityGate(cfg)
        candles = [_make_candle(has_gap=True, tick_count=1) for _ in range(50)]
        old_ts = time.time() - 100.0
        report = gate.assess("EURUSD", "M15", candles, last_update_ts=old_ts)
        assert report.confidence_penalty <= 0.25

    def test_lookback_window_limits_assessment(self) -> None:
        cfg = DataQualityConfig(lookback_candles=10)
        gate = DataQualityGate(cfg)
        # 90 good candles + 10 bad candles
        candles = [_make_candle() for _ in range(90)] + [_make_candle(has_gap=True) for _ in range(10)]
        report = gate.assess("EURUSD", "M15", candles, last_update_ts=time.time())
        assert report.total_candles == 10
        assert report.gap_candles == 10
        assert report.gap_ratio == 1.0

    def test_to_dict_serialization(self) -> None:
        gate = DataQualityGate()
        candles = [_make_candle() for _ in range(20)]
        report = gate.assess("EURUSD", "H1", candles, last_update_ts=time.time())
        d = report.to_dict()
        assert d["symbol"] == "EURUSD"
        assert d["timeframe"] == "H1"
        assert isinstance(d["reasons"], list)
        assert isinstance(d["confidence_penalty"], float)

    def test_combined_penalties(self) -> None:
        cfg = DataQualityConfig(
            max_gap_ratio=0.05,
            max_low_tick_ratio=0.05,
            stale_threshold_seconds=10.0,
            max_penalty=0.50,
        )
        gate = DataQualityGate(cfg)
        # Candles with gaps AND low tick counts
        candles = [_make_candle(has_gap=True, tick_count=1) for _ in range(50)]
        old_ts = time.time() - 300.0
        report = gate.assess("EURUSD", "M15", candles, last_update_ts=old_ts)
        assert report.degraded is True
        assert len(report.reasons) >= 2
