from __future__ import annotations

from analysis.data_quality_gate import DataQualityGate


def test_default_stale_multiplier_relaxed(monkeypatch):
    monkeypatch.delenv("WOLF_DQ_STALE_CANDLE_MULTIPLIER", raising=False)
    gate = DataQualityGate()

    threshold = gate._stale_threshold_for_timeframe("H1")

    assert threshold == 10800.0


def test_env_stale_multiplier_override(monkeypatch):
    monkeypatch.setenv("WOLF_DQ_STALE_CANDLE_MULTIPLIER", "2.0")
    gate = DataQualityGate()

    threshold = gate._stale_threshold_for_timeframe("H1")

    assert threshold == 7200.0
