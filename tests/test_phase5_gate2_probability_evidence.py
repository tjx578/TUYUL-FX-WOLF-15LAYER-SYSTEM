from __future__ import annotations

from pipeline.phases.gates import evaluate_9_gates


def _make_synthesis(*, hard_stop: bool = False, soft_blockers: list[str] | None = None) -> dict:
    return {
        "layers": {
            "L8_tii_sym": 0.95,
            "L7_monte_carlo_win": 0.75,
            "conf12": 0.85,
            "L8_integrity_index": 0.98,
        },
        "execution": {"rr_ratio": 2.0},
        "fusion_frpc": {"frpc_state": "SYNC"},
        "propfirm": {"compliant": True},
        "risk": {"current_drawdown": 2.0},
        "system": {"latency_ms": 100},
        "risk_of_ruin": 0.05,
        "probability_evidence": {
            "status": "FAIL" if hard_stop else "WARN",
            "hard_stop": hard_stop,
            "hard_blockers": ["REQUIRED_PROBABILITY_SOURCE_MISSING"] if hard_stop else [],
            "soft_blockers": soft_blockers or [],
            "evidence_score": 0.0 if hard_stop else 0.52,
            "confidence_penalty": 1.0 if hard_stop else 0.08,
        },
    }


def test_gate2_hard_stop_overrides_passing_analytical_metrics() -> None:
    gates = evaluate_9_gates(_make_synthesis(hard_stop=True))

    assert gates["gate_2_montecarlo"] == "FAIL"
    assert gates["gate_2_probability_evidence"] == "FAIL"


def test_gate2_soft_probability_evidence_does_not_force_fail() -> None:
    gates = evaluate_9_gates(_make_synthesis(hard_stop=False, soft_blockers=["WIN_PROBABILITY_NEAR_MISS"]))

    assert gates["gate_2_montecarlo"] == "PASS"
    assert gates["gate_2_probability_evidence"] == "PASS"
