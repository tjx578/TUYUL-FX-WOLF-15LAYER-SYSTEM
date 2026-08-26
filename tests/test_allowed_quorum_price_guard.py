"""Regression coverage for allowed-quorum DecisionUpdate price ownership."""

from __future__ import annotations

from datetime import UTC, datetime

from analysis.market_context_validator import MarketContext
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


class _FakeContextBus:
    def __init__(
        self,
        *,
        status: str = "LIVE",
        age_seconds: float | None = 0.0,
        timestamp: float | None = None,
        candles: dict[tuple[str, str], list[dict[str, object]]] | None = None,
    ) -> None:
        self.status = status
        self.age_seconds = age_seconds
        self.timestamp = timestamp
        self.candles = candles or {}

    def get_feed_status(self, symbol: str) -> str:
        return self.status

    def get_feed_age(self, symbol: str) -> float | None:
        return self.age_seconds

    def get_feed_timestamp(self, symbol: str) -> float | None:
        return self.timestamp

    def get_candle_history(self, symbol: str, timeframe: str, count: int | None = None) -> list[dict[str, object]]:
        candles = list(self.candles.get((symbol.upper(), timeframe.upper()), []))
        if count is not None and count < len(candles):
            return candles[-count:]
        return candles


def _pipeline() -> WolfConstitutionalPipeline:
    return WolfConstitutionalPipeline.__new__(WolfConstitutionalPipeline)


def _report() -> dict[str, object]:
    return {
        "allowed_quorum": {
            "symbol": "EURUSD",
            "direction": "BUY",
            "quorum_reached": True,
            "streak": 3,
        },
        "symbol_activity": {
            "EURUSD": {
                "latest_event_utc": "2026-06-09T14:49:04.357027+00:00",
                "latest_block_effective_ticks": 3,
            }
        },
    }


def test_allowed_quorum_requires_own_market_context_before_price_emit() -> None:
    payload = _pipeline()._allowed_quorum_decision_update_payload(
        symbol="EURUSD",
        synthesis={"execution": {"symbol": "NZDUSD", "entry_price": 0.58278}},
        l12_verdict={"verdict": "EXECUTE_BUY", "direction": "BUY"},
        report=_report(),
        market_contexts={},
        source_verdict="EXECUTE_BUY",
    )

    assert payload is None


def test_allowed_quorum_rejects_other_pair_market_context() -> None:
    payload = _pipeline()._allowed_quorum_decision_update_payload(
        symbol="EURUSD",
        synthesis={"execution": {"symbol": "EURJPY", "entry_price": 185.324}},
        l12_verdict={"verdict": "EXECUTE_BUY", "direction": "BUY"},
        report=_report(),
        market_contexts={
            "EURJPY": MarketContext(
                symbol="EURJPY",
                raw_allowed_direction="BUY",
                price_at_signal_end=185.324,
            )
        },
        source_verdict="EXECUTE_BUY",
    )

    assert payload is None


def test_allowed_quorum_uses_symbol_market_context_price_not_execution_fallback() -> None:
    market_context = MarketContext(
        symbol="EURUSD",
        raw_allowed_direction="BUY",
        price_at_signal_end=1.15627,
    )

    payload = _pipeline()._allowed_quorum_decision_update_payload(
        symbol="EURUSD",
        synthesis={"execution": {"symbol": "NZDUSD", "entry_price": 0.58278}},
        l12_verdict={"verdict": "EXECUTE_BUY", "direction": "BUY"},
        report=_report(),
        market_contexts={"EURUSD": market_context},
        source_verdict="EXECUTE_BUY",
    )

    assert payload is not None
    assert payload["symbol"] == "EURUSD"
    assert payload["market_context_applied"] is True
    assert payload["signal_valid_price"] == 1.15627
    assert payload["entry_reference_price"] == 1.15627
    assert payload["entry_zone"] == [1.15627, 1.15627]
    assert payload["reference_price"] == 1.15627
    assert payload["reference_price_role"] == "REFERENCE_ONLY_NOT_EXECUTABLE"
    assert payload["reference_price_status"] == "AVAILABLE"


def test_allowed_quorum_labels_stale_live_tick_reference_price() -> None:
    pipeline = _pipeline()
    tick_ts = datetime(2026, 7, 3, 2, 13, 15, tzinfo=UTC).timestamp()
    pipeline._context_bus = _FakeContextBus(
        status="STALE_PRESERVED",
        age_seconds=382.125,
        timestamp=tick_ts,
    )
    market_context = MarketContext(
        symbol="EURUSD",
        raw_allowed_direction="BUY",
        bid=1.1500,
        ask=1.1502,
        price_at_signal_end=1.1501,
    )

    payload = pipeline._allowed_quorum_decision_update_payload(
        symbol="EURUSD",
        synthesis={},
        l12_verdict={"verdict": "EXECUTE_BUY", "direction": "BUY"},
        report=_report(),
        market_contexts={"EURUSD": market_context},
        source_verdict="EXECUTE_BUY",
    )

    assert payload is not None
    assert payload["signal_valid_price"] == 1.1501
    assert payload["decision_price_role"] == "REFERENCE_ONLY_NOT_EXECUTABLE"
    assert payload["reference_price_used_for_decision_update"] == 1.1501
    assert payload["price_source"] == "LIVE_TICK_MID"
    assert payload["price_snapshot_time_utc"] == "2026-07-03T02:13:15+00:00"
    assert payload["price_age_seconds"] == 382.125
    assert payload["price_freshness_status"] == "STALE_PRESERVED"
    assert payload["quote_health_status"] == "PRICE_QUALITY_WARMING_UP"
    assert payload["quote_health_execution_blocked"] is True
    assert payload["reference_price_is_live"] is False
    assert payload["valid_for_execution"] is False
    assert payload["observed_price"] == 1.1501
    assert payload["observed_price_status"] == "STALE"
    assert payload["reference_price"] == 1.1501
    assert payload["reference_price_status"] == "STALE"
    assert payload["price_lineage_version"] == 2


def test_allowed_quorum_m15_reference_price_is_not_labeled_live() -> None:
    pipeline = _pipeline()
    pipeline._context_bus = _FakeContextBus(status="NO_PRODUCER", age_seconds=None, timestamp=None)
    market_context = MarketContext(
        symbol="EURUSD",
        raw_allowed_direction="BUY",
        price_at_signal_end=1.15627,
        price_at_5m_confirm=1.15627,
    )

    payload = pipeline._allowed_quorum_decision_update_payload(
        symbol="EURUSD",
        synthesis={},
        l12_verdict={"verdict": "EXECUTE_BUY", "direction": "BUY"},
        report=_report(),
        market_contexts={"EURUSD": market_context},
        source_verdict="EXECUTE_BUY",
    )

    assert payload is not None
    assert payload["signal_valid_price"] == 1.15627
    assert payload["price_source"] == "M15_CLOSE"
    assert payload["price_snapshot_time_utc"] is None
    assert payload["price_age_seconds"] is None
    assert payload["price_freshness_status"] == "NO_PRODUCER"
    assert payload["reference_price_is_live"] is False
    assert payload["observed_price"] == 1.15627
    assert payload["observed_price_source"] == "M15_CLOSE"
    assert payload["reference_price_status"] == "STALE"


def test_allowed_quorum_h1_reference_price_gets_candle_lineage() -> None:
    pipeline = _pipeline()
    candle_ts = datetime(2026, 7, 3, 1, 0, tzinfo=UTC).timestamp()
    pipeline._context_bus = _FakeContextBus(
        status="DEGRADED_BUT_REFRESHING",
        age_seconds=None,
        timestamp=None,
        candles={
            ("EURUSD", "H1"): [
                {
                    "symbol": "EURUSD",
                    "timeframe": "H1",
                    "close": 1.24125,
                    "timestamp": candle_ts,
                }
            ]
        },
    )
    market_context = MarketContext(
        symbol="EURUSD",
        raw_allowed_direction="BUY",
        price_at_signal_end=1.24125,
    )

    payload = pipeline._allowed_quorum_decision_update_payload(
        symbol="EURUSD",
        synthesis={},
        l12_verdict={"verdict": "EXECUTE_BUY", "direction": "BUY"},
        report=_report(),
        market_contexts={"EURUSD": market_context},
        source_verdict="EXECUTE_BUY",
    )

    assert payload is not None
    assert payload["signal_valid_price"] == 1.24125
    assert payload["price_source"] == "H1_CLOSE"
    assert payload["price_snapshot_time_utc"] == "2026-07-03T01:00:00+00:00"
    assert payload["price_age_seconds"] is not None
    assert payload["price_age_seconds"] >= 0.0
    assert payload["price_freshness_status"] == "DEGRADED_BUT_REFRESHING"
    assert payload["reference_price_is_live"] is False
