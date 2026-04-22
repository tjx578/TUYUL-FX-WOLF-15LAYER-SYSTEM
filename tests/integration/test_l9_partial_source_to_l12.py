"""Integration test for L9 partial structure evidence propagation into L12."""

from __future__ import annotations

import pytest

from analysis.layers.L9_constitutional import L9ConstitutionalGovernor
from constitution.l12_router_evaluator import L12BlockerCode, L12RouterEvaluator, build_l12_input_from_upstream


def _l9_analysis() -> dict:
    return {
        "symbol": "EURUSD",
        "smc_score": 85,
        "liquidity_score": 0.75,
        "dvg_confidence": 0.0,
        "smart_money_bias": "BULLISH",
        "smart_money_signal": "ACCUMULATION",
        "ob_present": True,
        "fvg_present": True,
        "sweep_detected": True,
        "confidence": 0.85,
        "valid": True,
        "smc": True,
        "bos_detected": True,
        "choch_detected": False,
        "displacement": True,
        "liquidity_sweep": True,
        "reason": "smc_ok",
    }


def _build_upstream(l9_layer: dict) -> dict:
    return {
        "input_ref": "EURUSD_H1_l9_partial",
        "timestamp": "2026-04-22T13:00:00+00:00",
        "continuation_allowed": True,
        "next_legal_targets": ["PHASE_5"],
        "phase4_result": {
            "chain_status": "PASS",
            "summary_status": {"L11": "PASS", "L6": "PASS", "L10": "PASS"},
            "layer_results": {"L11": {"score_numeric": 0.85}, "L6": {"score_numeric": 0.90}, "L10": {"score_numeric": 0.80}},
        },
        "upstream_result": {
            "upstream_result": {
                "upstream_result": {
                    "phase_results": {
                        "PHASE_1": {
                            "chain_status": "PASS",
                            "summary_status": {"L1": "PASS", "L2": "PASS", "L3": "PASS"},
                            "layer_results": {"L1": {"score_numeric": 0.91}, "L2": {"score_numeric": 0.88}, "L3": {"score_numeric": 0.87}},
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
                "chain_status": "WARN",
                "summary_status": {"L7": "PASS", "L8": "PASS", "L9": "WARN"},
                "layer_results": {"L7": {"score_numeric": 0.75}, "L8": {"score_numeric": 0.92}, "L9": l9_layer},
            },
        },
    }


@pytest.mark.integration
def test_l9_partial_source_reaches_l12_as_soft_structure_evidence() -> None:
    l9 = L9ConstitutionalGovernor().evaluate(_l9_analysis(), {"valid": True, "continuation_allowed": True})

    assert l9["status"] == "WARN"
    assert l9["hard_stop"] is False
    assert "DIVERGENCE_SOURCE_MISSING" in l9["soft_blockers"]

    l12_input = build_l12_input_from_upstream(_build_upstream(l9))
    result = L12RouterEvaluator().evaluate(l12_input)

    assert "L9_WEAK_STRUCTURE_EVIDENCE" in result.warning_codes
    assert "L9_SOURCE_BUILDER_PARTIAL" in result.warning_codes
    assert L12BlockerCode.L9_HARD_STRUCTURE_ILLEGALITY.value not in result.blocker_codes