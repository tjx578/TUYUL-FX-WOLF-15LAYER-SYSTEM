"""Regression coverage for allowed-quorum DecisionUpdate price ownership."""

from __future__ import annotations

from analysis.market_context_validator import MarketContext
from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


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
