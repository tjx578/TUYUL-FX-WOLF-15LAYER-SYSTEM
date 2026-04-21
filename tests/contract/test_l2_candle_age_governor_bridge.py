from __future__ import annotations

from typing import Any, cast

from analysis.layers.L2_mta import L2MTAAnalyzer


def _candle(timestamp: str, close: float) -> dict[str, float | str]:
    return {
        "symbol": "EURUSD",
        "open": close - 0.001,
        "high": close + 0.001,
        "low": close - 0.002,
        "close": close,
        "timestamp": timestamp,
    }


class _FakeBus:
    def __init__(self) -> None:
        self._latest = {
            "MN": _candle("2026-03-01T00:00:00Z", 1.1000),
            "W1": _candle("2026-04-14T00:00:00Z", 1.1010),
            "D1": _candle("2026-04-16T00:00:00Z", 1.1020),
            "H4": _candle("2026-04-21T00:00:00Z", 1.1030),
            "H1": _candle("2026-04-21T10:00:00Z", 1.1040),
            "M15": _candle("2026-04-21T11:45:00Z", 1.1045),
        }
        self._history = {
            "MN": [dict(self._latest["MN"]) for _ in range(2)],
            "W1": [dict(self._latest["W1"]) for _ in range(5)],
            "D1": [dict(self._latest["D1"]) for _ in range(6)],
            "H4": [dict(self._latest["H4"]) for _ in range(12)],
            "H1": [dict(self._latest["H1"]) for _ in range(30)],
            "M15": [dict(self._latest["M15"]) for _ in range(40)],
        }

    def get_candle(self, symbol: str, timeframe: str):
        return dict(self._latest[timeframe])

    def get_candle_history(self, symbol: str, timeframe: str):
        return list(self._history.get(timeframe, []))

    def get_layer_cache(self, layer: str, symbol: str):
        return {"regime": "TREND_UP", "volatility_level": "NORMAL"}


def test_l2_passes_conservative_htf_candle_age_and_counts(monkeypatch):
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

    monkeypatch.setattr("analysis.layers.L2_constitutional.L2ConstitutionalGovernor", _FakeGovernor)

    analyzer = L2MTAAnalyzer()
    analyzer.bus = _FakeBus()

    result = analyzer.analyze("EURUSD")

    candle_counts = cast(dict[str, int], captured["candle_counts"])
    l2_analysis = cast(dict[str, Any], captured["l2_analysis"])
    candle_age_by_tf = cast(dict[str, float | None], l2_analysis["candle_age_by_tf"])

    assert result["valid"] is True
    assert captured["symbol"] == "EURUSD"
    assert captured["candle_age_seconds"] is not None
    assert captured["candle_age_seconds"] > 72_000
    assert candle_counts["D1"] == 6
    assert candle_counts["H4"] == 12
    assert candle_counts["H1"] == 30
    assert candle_age_by_tf["D1"] is not None
