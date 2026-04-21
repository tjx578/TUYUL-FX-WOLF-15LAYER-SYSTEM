from __future__ import annotations

from analysis.layers.L8_constitutional import L8ConstitutionalGovernor


def _upstream_pass() -> dict:
    return {"valid": True, "continuation_allowed": True}


def test_l8_fail_exposes_integrity_diagnostics_without_changing_status() -> None:
    gov = L8ConstitutionalGovernor()
    result = gov.evaluate(
        {
            "symbol": "NZDUSD",
            "tii_sym": 0.5,
            "tii_status": "WEAK",
            "tii_grade": "WEAK",
            "integrity": 0.5,
            "twms_score": 0.42,
            "gate_status": "CLOSED",
            "gate_passed": False,
            "valid": True,
            "components": {"trend": 0.4, "momentum": 0.3},
            "twms_signals": {"rsi": "SELL"},
            "computed_vwap": 1.12345,
            "computed_energy": 4.2,
            "computed_bias": -0.001,
        },
        _upstream_pass(),
    )

    assert result["status"] == "FAIL"
    assert "INTEGRITY_SCORE_BELOW_MINIMUM" in result["blocker_codes"]
    diagnostics = result["integrity_diagnostics"]
    assert diagnostics["primary_integrity_gap"] == "INTEGRITY_SCORE_BELOW_MINIMUM"
    assert diagnostics["required_integrity"] == 0.75
    assert diagnostics["component_count"] == 2
    assert diagnostics["missing_sources"] == []


def test_l8_pass_still_exposes_integrity_diagnostics() -> None:
    gov = L8ConstitutionalGovernor()
    result = gov.evaluate(
        {
            "symbol": "EURJPY",
            "tii_sym": 0.92,
            "tii_status": "STRONG",
            "tii_grade": "STRONG",
            "integrity": 0.9,
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
            "twms_signals": {"rsi": "BUY"},
            "computed_vwap": 1.12345,
            "computed_energy": 5.1,
            "computed_bias": 0.002,
        },
        _upstream_pass(),
    )

    assert result["status"] == "PASS"
    diagnostics = result["integrity_diagnostics"]
    assert diagnostics["primary_integrity_gap"] is None
    assert diagnostics["integrity_score"] == 0.9
    assert diagnostics["available_sources"] == ["tii", "twms", "components"]
