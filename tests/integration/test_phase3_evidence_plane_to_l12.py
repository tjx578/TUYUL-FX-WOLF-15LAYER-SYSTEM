"""Integration tests for Phase 3 combined evidence propagation into L12."""

from __future__ import annotations

import pytest

from analysis.layers.L7_constitutional import L7ConstitutionalGovernor
from analysis.layers.L8_constitutional import L8ConstitutionalGovernor
from analysis.layers.L9_constitutional import L9ConstitutionalGovernor
from constitution.l12_router_evaluator import L12BlockerCode, L12RouterEvaluator, build_l12_input_from_upstream


def _l7_soft_analysis() -> dict:
    return {
        "symbol": "EURUSD",
        "win_probability": 52.0,
        "profit_factor": 1.4,
        "simulations": 1000,
        "validation": "PASS",
        "valid": True,
        "mc_passed_threshold": True,
        "risk_of_ruin": 0.04,
        "conf12_raw": 0.71,
        "bayesian_posterior": 0.58,
        "returns_source": "trade_history",
        "wf_passed": True,
    }


def _l8_soft_layer() -> dict:
    upstream = {
        "valid": True,
        "continuation_allowed": True,
        "l2_context": {
            "status": "WARN",
            "hard_stop": False,
            "soft_blockers": ["LOW_ALIGNMENT_BAND"],
            "hard_blockers": [],
            "confidence_penalty": 0.25,
        },
    }
    return L8ConstitutionalGovernor().evaluate(
        {
            "symbol": "EURUSD",
            "valid": True,
            "integrity": 0.92,
            "tii_sym": 0.94,
            "twms_score": 0.88,
            "gate_status": "OPEN",
            "gate_passed": True,
            "tii_status": "STRONG",
            "core_enhanced": True,
            "computed_vwap": 1.085,
            "components": {"tii": 0.94, "twms": 0.88, "energy": 0.9},
        },
        upstream,
    )


def _l9_soft_analysis() -> dict:
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


def _base_upstream(l7_layer: dict, l8_layer: dict, l9_layer: dict, *, phase3_status: str) -> dict:
    return {
        "input_ref": "EURUSD_H1_phase3_full",
        "timestamp": "2026-04-22T14:00:00+00:00",
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
                            "chain_status": "WARN",
                            "summary_status": {"L1": "PASS", "L2": "WARN", "L3": "PASS"},
                            "layer_results": {
                                "L1": {"score_numeric": 0.91},
                                "L2": {
                                    "score_numeric": 0.88,
                                    "evidence_score": 0.52,
                                    "confidence_penalty": 0.25,
                                    "status": "WARN",
                                    "advisory_continuation": True,
                                    "hard_stop": False,
                                    "hard_blockers": [],
                                    "soft_blockers": ["LOW_ALIGNMENT_BAND", "STRUCTURE_NOT_FULLY_ALIGNED"],
                                },
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
                "chain_status": phase3_status,
                "summary_status": {"L7": l7_layer["status"], "L8": l8_layer["status"], "L9": l9_layer["status"]},
                "layer_results": {"L7": l7_layer, "L8": l8_layer, "L9": l9_layer},
            },
        },
    }


@pytest.mark.integration
def test_phase3_soft_stack_reaches_l12_as_warnings() -> None:
    l7 = L7ConstitutionalGovernor().evaluate(_l7_soft_analysis(), {"valid": True, "continuation_allowed": True})
    l8 = _l8_soft_layer()
    l9 = L9ConstitutionalGovernor().evaluate(_l9_soft_analysis(), {"valid": True, "continuation_allowed": True})

    assert l7["status"] == "WARN"
    assert l8["status"] == "WARN"
    assert l9["status"] == "WARN"

    l12_input = build_l12_input_from_upstream(_base_upstream(l7, l8, l9, phase3_status="WARN"))
    result = L12RouterEvaluator().evaluate(l12_input)

    assert "L7_WEAK_PROBABILITY_EVIDENCE" in result.warning_codes
    assert "UPSTREAM_L2_WEAK_EVIDENCE" in result.warning_codes or "INTEGRITY_OK_WARN" in result.warning_codes
    assert "L9_WEAK_STRUCTURE_EVIDENCE" in result.warning_codes
    assert L12BlockerCode.L7_HARD_PROBABILITY_ILLEGALITY.value not in result.blocker_codes
    assert L12BlockerCode.L9_HARD_STRUCTURE_ILLEGALITY.value not in result.blocker_codes


@pytest.mark.integration
def test_phase3_hard_probability_blocks_l12() -> None:
    l7 = L7ConstitutionalGovernor().evaluate(
        {
            "symbol": "EURUSD",
            "win_probability": 0.0,
            "profit_factor": 0.0,
            "simulations": 0,
            "validation": "FAIL",
            "valid": True,
            "mc_passed_threshold": False,
            "risk_of_ruin": 1.0,
            "conf12_raw": 0.0,
            "bayesian_posterior": 0.0,
            "returns_source": "trade_history",
            "wf_passed": True,
            "note": "insufficient_data_5/30",
        },
        {"valid": True, "continuation_allowed": True},
    )
    l8 = _l8_soft_layer()
    l9 = L9ConstitutionalGovernor().evaluate(_l9_soft_analysis(), {"valid": True, "continuation_allowed": True})

    assert l7["hard_stop"] is True

    l12_input = build_l12_input_from_upstream(_base_upstream(l7, l8, l9, phase3_status="FAIL"))
    result = L12RouterEvaluator().evaluate(l12_input)

    assert result.verdict == "NO_TRADE"
    assert L12BlockerCode.L7_HARD_PROBABILITY_ILLEGALITY.value in result.blocker_codes