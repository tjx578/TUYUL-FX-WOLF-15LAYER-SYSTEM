from __future__ import annotations

from analysis.layers.L1_constitutional import L1GateInput, evaluate_l1_constitutional


def test_l1_fail_exposes_context_diagnostics_without_changing_status() -> None:
    result = evaluate_l1_constitutional(
        L1GateInput(
            analysis_result={
                "valid": True,
                "regime": "TREND_UP",
                "context_coherence": 0.42,
                "regime_probability": 0.58,
                "dominant_force": "BULLISH",
                "feature_spread": 0.0012,
                "feature_atr_frac": 0.0008,
                "feature_hurst": 0.63,
                "feature_zscore": 0.41,
            },
            symbol="EURUSD",
            feed_timestamp=0.0,
            candle_counts={"H1": 20, "H4": 10, "D1": 5, "W1": 5, "MN": 2},
            producer_available=True,
            snapshot_valid=True,
            session_state_valid=True,
            regime_service_available=True,
            context_sources_used=["context_bus", "session_state"],
        )
    ).to_dict()

    assert result["status"] == "FAIL"
    assert "LOW_CONTEXT_COHERENCE" in result["blocker_codes"]
    diagnostics = result["context_diagnostics"]
    assert diagnostics["regime"] == "TREND_UP"
    assert diagnostics["required_coherence"] == 0.65
    assert diagnostics["trend_regime_requires_block"] is True
    assert diagnostics["missing_warmup_by_tf"] == {}


def test_l1_warn_still_exposes_context_diagnostics() -> None:
    result = evaluate_l1_constitutional(
        L1GateInput(
            analysis_result={
                "valid": True,
                "regime": "RANGE",
                "context_coherence": 0.42,
                "regime_probability": 0.44,
                "dominant_force": "NEUTRAL",
            },
            symbol="AUDCAD",
            feed_timestamp=0.0,
            candle_counts={"H1": 25, "H4": 12, "D1": 6, "W1": 5, "MN": 2},
            producer_available=True,
            snapshot_valid=True,
            session_state_valid=True,
            regime_service_available=True,
            context_sources_used=["context_bus"],
        )
    ).to_dict()

    assert result["status"] == "WARN"
    diagnostics = result["context_diagnostics"]
    assert diagnostics["regime"] == "RANGE"
    assert diagnostics["trend_regime_requires_block"] is False
    assert diagnostics["missing_warmup_by_tf"] == {}
