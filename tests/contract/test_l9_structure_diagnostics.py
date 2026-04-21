from __future__ import annotations

from analysis.layers.L9_constitutional import L9ConstitutionalGovernor


def _upstream_pass() -> dict:
    return {"valid": True, "continuation_allowed": True}


def test_l9_fail_exposes_structure_diagnostics_without_changing_status() -> None:
    gov = L9ConstitutionalGovernor()
    result = gov.evaluate(
        {
            "symbol": "USDCAD",
            "smc_score": 0,
            "liquidity_score": 0.0,
            "dvg_confidence": 0.0,
            "confidence": 0.0,
            "valid": False,
            "smc": False,
            "reason": "no_structure_data",
            "warmup_required_bars": {"H1": 100, "H4": 50, "D1": 20},
            "warmup_available_bars": {"H1": 44, "H4": 80, "D1": 10},
            "source_builder_state": "not_ready",
        },
        _upstream_pass(),
    )

    assert result["status"] == "FAIL"
    assert "REQUIRED_STRUCTURE_SOURCE_MISSING" in result["blocker_codes"]
    diagnostics = result["structure_diagnostics"]
    assert diagnostics["missing_sources"] == ["smc", "liquidity", "divergence"]
    assert diagnostics["warmup_required_bars"] == {"H1": 100, "H4": 50, "D1": 20}
    assert diagnostics["warmup_available_bars"] == {"H1": 44, "H4": 80, "D1": 10}
    assert diagnostics["source_builder_state"] == "not_ready"


def test_l9_pass_still_exposes_structure_diagnostics() -> None:
    gov = L9ConstitutionalGovernor()
    result = gov.evaluate(
        {
            "symbol": "EURUSD",
            "smc_score": 87,
            "liquidity_score": 0.73,
            "dvg_confidence": 0.81,
            "confidence": 0.84,
            "valid": True,
            "smc": True,
            "bos_detected": True,
            "choch_detected": False,
            "fvg_present": True,
            "ob_present": True,
            "sweep_detected": True,
            "reason": "smc_ok",
        },
        _upstream_pass(),
    )

    assert result["status"] == "PASS"
    diagnostics = result["structure_diagnostics"]
    assert diagnostics["available_sources"] == ["smc", "liquidity", "divergence"]
    assert diagnostics["missing_sources"] == []
    assert diagnostics["source_builder_state"] == "ready"
