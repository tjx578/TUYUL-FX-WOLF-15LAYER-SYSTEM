from __future__ import annotations

from typing import Any

from analysis.universe_ranking import UniverseRankingEngine
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


def _make_candles(start: float, pct_change: float, count: int = 50) -> list[dict[str, Any]]:
    if count <= 1:
        return [{"close": start}]
    return [
        {"open": start, "high": start, "low": start, "close": start * (1.0 + pct_change * (idx / (count - 1)))}
        for idx in range(count)
    ]


class _Bus:
    def __init__(self, candles: dict[str, list[dict[str, Any]]]) -> None:
        self._candles = {key.upper(): value for key, value in candles.items()}

    def get_candle_history(self, symbol: str, timeframe: str, count: int | None = None) -> list[dict[str, Any]]:
        data = list(self._candles.get(symbol.upper(), []))
        return data[-count:] if count is not None else data

    def get_candles(self, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        return list(self._candles.get(symbol.upper(), []))


def _nzd_strong_jpy_weak_bus() -> _Bus:
    candles: dict[str, list[dict[str, Any]]] = {}
    for pair in ("USDJPY", "EURJPY", "GBPJPY", "AUDJPY", "NZDJPY", "CADJPY", "CHFJPY"):
        candles[pair] = _make_candles(100.0, 0.035)
    for pair in ("NZDUSD", "NZDCHF", "NZDCAD"):
        candles[pair] = _make_candles(1.0, 0.030)
    for pair in ("EURNZD", "GBPNZD", "AUDNZD"):
        candles[pair] = _make_candles(1.0, -0.025)
    candles["EURUSD"] = _make_candles(1.0, 0.002)
    candles["GBPUSD"] = _make_candles(1.0, 0.006)
    candles["USDCAD"] = _make_candles(1.0, 0.004)
    return _Bus(candles)


def test_universe_ranking_produces_conditional_watchlist_for_nzdjpy() -> None:
    engine = UniverseRankingEngine(
        pair_universe=(
            "EURUSD",
            "GBPUSD",
            "USDJPY",
            "EURJPY",
            "GBPJPY",
            "AUDJPY",
            "NZDJPY",
            "CADJPY",
            "CHFJPY",
            "NZDUSD",
            "NZDCHF",
            "NZDCAD",
            "EURNZD",
            "GBPNZD",
            "AUDNZD",
        )
    )

    result = engine.analyze(_nzd_strong_jpy_weak_bus(), target_symbol="NZDJPY", warmup={"ready": True})

    assert result.data_ready is True
    assert result.target_rank is not None
    assert result.target_rank.symbol == "NZDJPY"
    assert result.target_rank.bias == "BUY"
    assert result.target_rank.rank <= 5
    assert result.target_rank.watchlist_status in {
        "VALID_BERSYARAT",
        "VALID_ON_PULLBACK",
        "WAIT_RECLAIM",
        "CADANGAN",
    }


def test_universe_ranking_marks_snapshot_not_ready_when_warmup_fails() -> None:
    engine = UniverseRankingEngine(pair_universe=("NZDJPY", "USDJPY", "NZDUSD", "EURNZD"))

    result = engine.analyze(
        _nzd_strong_jpy_weak_bus(),
        target_symbol="NZDJPY",
        warmup={"ready": False},
    )

    assert result.data_ready is False
    assert "warmup_not_ready" in result.readiness_reasons
    assert result.target_rank is not None
    assert result.target_rank.watchlist_status == "DATA_NOT_READY_FOR_RANKING"


def test_pipeline_l12_annotation_marks_ranked_target_executable() -> None:
    ranking = {
        "target_symbol": "NZDJPY",
        "target_rank": {"symbol": "NZDJPY", "watchlist_status": "VALID_ON_PULLBACK"},
        "top_pairs": [{"symbol": "NZDJPY", "watchlist_status": "VALID_ON_PULLBACK"}],
        "ranked_pairs": [{"symbol": "NZDJPY", "watchlist_status": "VALID_ON_PULLBACK"}],
    }

    WolfConstitutionalPipeline._annotate_universe_ranking_with_l12(
        ranking,
        {"verdict": "EXECUTE_BUY", "continuation_allowed": True},
    )

    assert ranking["target_rank"]["l12_verdict"] == "EXECUTE_BUY"
    assert ranking["target_rank"]["execution_allowed"] is True
    assert ranking["target_rank"]["watchlist_status"] == "EXECUTABLE"
    assert ranking["top_pairs"][0]["watchlist_status"] == "EXECUTABLE"
