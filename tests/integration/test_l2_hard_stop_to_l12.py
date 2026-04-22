"""Integration test for L2 hard stop propagation through L8 into L12."""

from __future__ import annotations

import pytest

from analysis.layers.L8_constitutional import L8BlockerCode, L8ConstitutionalGovernor
from constitution.l12_router_evaluator import L12BlockerCode, L12RouterEvaluator, build_l12_input_from_upstream


def _l8_analysis() -> dict:
    return {
        "tii_sym": 0.92,
        "tii_status": "STRONG",
        "tii_grade": "STRONG",
        "integrity": 0.90,
        "twms_score": 0.85,
        "gate_status": "OPEN",
        "gate_passed": True,
        "valid": True,
        "components": {
            "trend": 0.8,
            "momentum": 0.7,
            "volatility": 0.6,
            "volume": 0.5,
            "correlation": 0.4,
            "rsi": 0.6,
            "macd": 0.7,
            "cci": 0.5,
            "mfi": 0.6,
            "atr": 0.8,
        },
        "twms_signals": {"rsi": "BUY", "macd": "BUY", "cci": "NEUTRAL"},
        "computed_vwap": 1.12345,
        "computed_energy": 5.5,
        "computed_bias": 0.002,
        "note": "",
        "core_enhanced": False,
        "symbol": "EURUSD",
    }


def _phase4_result() -> dict:
    return {
        "chain_status": "PASS",
        "summary_status": {"L11": "PASS", "L6": "PASS", "L10": "PASS"},
        "layer_results": {
            "L11": {"score_numeric": 0.85},
            "L6": {"score_numeric": 0.90},
            "L10": {"score_numeric": 0.80},
        },
    }


def _build_upstream(*, l2_layer: dict, l8_layer: dict) -> dict:
    return {
        "input_ref": "EURUSD_H1_integration_hard",
        "timestamp": "2026-04-22T12:05:00+00:00",
        "continuation_allowed": True,
        "next_legal_targets": ["PHASE_5"],
        "phase4_result": _phase4_result(),
        "upstream_result": {
            "upstream_result": {
                "upstream_result": {
                    "phase_results": {
                        "PHASE_1": {
                            "chain_status": "FAIL",
                            "summary_status": {"L1": "PASS", "L2": "FAIL", "L3": "PASS"},
                            "layer_results": {
                                "L1": {"score_numeric": 0.91},
                                "L2": l2_layer,
                                "L3": {"score_numeric": 0.87},
                            },
                        },
                        "PHASE_2": {
                            "chain_status": "PASS",
                            "summary_status": {"L4": "PASS", "L5": "PASS"},
                            "layer_results": {"L4": {"score_numeric": 0.82}, "L5": {"score_numeric": 0.78}},
                        },
                    },
                },
                "phase25_result": {"phase_status": "PASS"},
            },
            "phase3_result": {
                "chain_status": "FAIL",
                "summary_status": {"L7": "PASS", "L8": l8_layer["status"], "L9": "PASS"},
                "layer_results": {
                    "L7": {"score_numeric": 0.75},
                    "L8": l8_layer,
                    "L9": {"score_numeric": 0.80},
                },
            },
        },
    }


@pytest.mark.integration
def test_l2_hard_stop_surfaces_as_l8_blocker_and_l12_no_trade() -> None:
    l2_layer = {
        "status": "FAIL",
        "score_numeric": 0.0,
        "evidence_score": 0.0,
        "confidence_penalty": 1.0,
        "hard_stop": True,
        "advisory_continuation": False,
        "hard_blockers": ["REQUIRED_TIMEFRAME_MISSING"],
        "soft_blockers": [],
    }
    l8 = L8ConstitutionalGovernor().evaluate(
        _l8_analysis(),
        upstream_output={
            "valid": True,
            "continuation_allowed": True,
            "l2_context": l2_layer,
        },
    )

    assert l8["status"] == "FAIL"
    assert L8BlockerCode.UPSTREAM_L2_HARD_STOP.value in l8["blocker_codes"]

    l12_input = build_l12_input_from_upstream(_build_upstream(l2_layer=l2_layer, l8_layer=l8))
    result = L12RouterEvaluator().evaluate(l12_input)

    assert result.verdict == "NO_TRADE"
    assert L12BlockerCode.L2_HARD_ILLEGALITY.value in result.blocker_codes
    assert result.audit["l2_evidence"]["hard_blockers"] == ["REQUIRED_TIMEFRAME_MISSING"]