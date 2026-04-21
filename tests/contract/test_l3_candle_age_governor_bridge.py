from __future__ import annotations

from typing import Any, cast

from analysis.layers.L3_technical import L3TechnicalAnalyzer


def _candle(timestamp: str, close: float, index: int) -> dict[str, float | str]:
    return {
        "symbol": "EURUSD",
        "timeframe": "H1",
        "open": close - 0.0010,
        "high": close + 0.0020,
        "low": close - 0.0020,
        "close": close,
        "volume": float(1000 + index),
        "timestamp": timestamp,
    }


class _FakeBus:
    def __init__(self) -> None:
        self._h1 = [_candle(f"2026-04-{day:02d}T10:00:00Z", 1.10 + (day * 0.0003), day) for day in range(1, 31)]
        self._h4 = [_candle(f"2026-04-{day:02d}T00:00:00Z", 1.20 + (day * 0.0005), day) for day in range(1, 31)]
        self._d1 = [_candle(f"2026-04-{day:02d}T00:00:00Z", 1.30 + (day * 0.0007), day) for day in range(1, 16)]

    def get_candle_history(self, symbol: str, timeframe: str, count: int | None = None):
        data = {
            "H1": self._h1,
            "H4": self._h4,
            "D1": self._d1,
        }[timeframe]
        if count is not None and count < len(data):
            return list(data[-count:])
        return list(data)


class _FakeLiquidityResult:
    def __init__(self, sweep_quality: float) -> None:
        self.sweep_quality = sweep_quality


def test_l3_passes_htf_candle_age_to_governor(monkeypatch):
    captured: dict[str, Any] = {}

    class _FakeGovernor:
        def evaluate(self, **kwargs):
            captured.update(kwargs)
            return {
                "continuation_allowed": True,
                "status": "PASS",
                "features": {},
                "routing": {},
                "warning_codes": [],
                "blocker_codes": [],
            }

    monkeypatch.setattr("analysis.layers.L3_constitutional.L3ConstitutionalGovernor", _FakeGovernor)

    analyzer = L3TechnicalAnalyzer(l2_output={"valid": True, "continuation_allowed": True})
    cast(Any, analyzer)._bus = _FakeBus()

    def _fake_score(candles: list[dict[str, Any]], direction: str = "bullish") -> _FakeLiquidityResult:
        return _FakeLiquidityResult(0.4)

    monkeypatch.setattr(analyzer._liq, "score", _fake_score)

    result = analyzer.analyze("EURUSD")

    l3_analysis = cast(dict[str, Any], captured["l3_analysis"])
    candle_age_by_tf = cast(dict[str, float | None], l3_analysis["candle_age_by_tf"])

    assert result["valid"] is True
    assert captured["symbol"] == "EURUSD"
    assert captured["candle_age_seconds"] is not None
    assert captured["candle_age_seconds"] > 72_000
    assert captured["h1_bar_count"] >= 30
    assert candle_age_by_tf["D1"] is not None
    assert candle_age_by_tf["H4"] is not None
    assert candle_age_by_tf["H1"] is not None
