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
    assert diagnostics["component_attribution"]["l2_alignment_component"] == 0.0
    assert diagnostics["component_attribution"]["l7_probability_component"] == 0.0
    assert diagnostics["component_attribution"]["unavailable_components"] == ["l9_structure_component"]


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
    # PR-4 source-aware fields
    assert diagnostics["required_sources"] == ["tii", "twms", "components"]
    assert diagnostics["source_completeness"] == 1.0
    assert diagnostics["source_completeness_threshold"] == 0.80
    assert diagnostics["integrity_mode"] == "FULL"
    assert diagnostics["component_attribution"]["tii_component"] == 0.92
    assert diagnostics["component_attribution"]["twms_component"] == 0.85
    assert result["integrity_mode"] == "FULL"
    assert result["source_completeness"] == 1.0


def test_l8_source_incomplete_fails_with_explicit_blocker_and_mode() -> None:
    """PR-4: valid-but-incomplete sources must FAIL with source-aware blocker.

    Raw fields look healthy (tii_sym, twms_score present), but an empty
    components dict drops completeness to 2/3 (~0.667), below the 0.80
    required threshold. Governor must not accept the high integrity score
    at face value.
    """
    gov = L8ConstitutionalGovernor()
    result = gov.evaluate(
        {
            "symbol": "EURUSD",
            "tii_sym": 0.92,
            "tii_status": "STRONG",
            "tii_grade": "STRONG",
            "integrity": 0.90,
            "twms_score": 0.85,
            "gate_status": "OPEN",
            "gate_passed": True,
            "valid": True,
            "components": {},
            "twms_signals": {"rsi": "BUY"},
            "computed_vwap": 1.12345,
            "computed_energy": 5.1,
            "computed_bias": 0.002,
        },
        _upstream_pass(),
    )

    assert result["status"] == "FAIL"
    assert "INTEGRITY_SOURCE_INCOMPLETE" in result["blocker_codes"]
    assert result["integrity_mode"] == "PARTIAL"
    assert result["source_completeness"] < 0.80
    assert "PARTIAL_INTEGRITY_SOURCES" in result["warning_codes"]
    diagnostics = result["integrity_diagnostics"]
    assert diagnostics["primary_integrity_gap"] == "INTEGRITY_SOURCE_INCOMPLETE"
    assert diagnostics["integrity_mode"] == "PARTIAL"
    assert "components" in diagnostics["missing_sources"]
