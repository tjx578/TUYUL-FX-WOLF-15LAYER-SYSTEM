from __future__ import annotations

from analysis.layers.L7_constitutional import L7ConstitutionalGovernor


def _upstream_pass() -> dict:
    return {"valid": True, "continuation_allowed": True}


def test_l7_fail_exposes_edge_diagnostics_without_changing_status() -> None:
    gov = L7ConstitutionalGovernor()
    result = gov.evaluate(
        {
            "symbol": "GBPUSD",
            "win_probability": 45.0,
            "profit_factor": 0.82,
            "simulations": 1000,
            "validation": "FAIL",
            "valid": True,
            "mc_passed_threshold": False,
            "risk_of_ruin": 0.22,
            "conf12_raw": 0.41,
            "bayesian_posterior": 0.48,
            "returns_source": "trade_history",
            "wf_passed": False,
        },
        _upstream_pass(),
    )

    assert result["status"] == "FAIL"
    assert "EDGE_STATUS_INVALID" in result["blocker_codes"]
    diagnostics = result["edge_diagnostics"]
    assert diagnostics["edge_status"] == "FAIL"
    assert diagnostics["primary_edge_gap"] == "EDGE_STATUS_INVALID"
    assert diagnostics["required_win_probability"] == 0.55
    assert diagnostics["simulations"] == 1000


def test_l7_pass_still_exposes_edge_diagnostics() -> None:
    gov = L7ConstitutionalGovernor()
    result = gov.evaluate(
        {
            "symbol": "EURUSD",
            "win_probability": 72.0,
            "profit_factor": 2.1,
            "simulations": 1000,
            "validation": "PASS",
            "valid": True,
            "mc_passed_threshold": True,
            "risk_of_ruin": 0.02,
            "conf12_raw": 0.92,
            "bayesian_posterior": 0.68,
            "returns_source": "trade_history",
            "wf_passed": True,
        },
        _upstream_pass(),
    )

    assert result["status"] == "PASS"
    diagnostics = result["edge_diagnostics"]
    assert diagnostics["edge_status"] == "PASS"
    assert diagnostics["primary_edge_gap"] is None
    assert diagnostics["win_probability"] == 0.72
