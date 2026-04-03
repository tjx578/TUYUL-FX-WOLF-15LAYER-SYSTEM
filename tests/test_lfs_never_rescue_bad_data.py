"""Tests for LFS rescue — negative cases.

Verifies that borderline scores with degraded/stale/insufficient conditions
are NOT rescued, even when ENABLE_L8_LFS_RESCUE is on.
"""

from __future__ import annotations

from unittest.mock import patch

from analysis.layers.L8_constitutional import (
    L8ConstitutionalGovernor,
    L8Status,
)

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _l8_borderline(
    *,
    integrity: float = 0.738,
    has_lorentzian: bool = True,
    lrce: float = 0.972,
    drift: float = 0.003,
    rescue_eligible: bool = True,
    # extra overrides for degradation
    tii_status: str = "ACCEPTABLE",
    tii_grade: str = "ACCEPTABLE",
    valid: bool = True,
    gate_passed: bool = True,
    gate_status: str = "OPEN",
) -> dict:
    base = {
        "tii_sym": 0.80,
        "tii_status": tii_status,
        "tii_grade": tii_grade,
        "integrity": integrity,
        "twms_score": 0.70,
        "gate_status": gate_status,
        "gate_passed": gate_passed,
        "valid": valid,
        "components": {
            "trend": 0.7,
            "momentum": 0.6,
            "volatility": 0.5,
            "volume": 0.5,
            "correlation": 0.4,
            "rsi": 0.6,
            "macd": 0.6,
            "cci": 0.5,
            "mfi": 0.5,
            "atr": 0.7,
        },
        "twms_signals": {"rsi": "BUY", "macd": "NEUTRAL"},
        "computed_vwap": 1.12345,
        "computed_energy": 4.0,
        "computed_bias": 0.001,
        "note": "",
        "symbol": "EURUSD",
    }
    if has_lorentzian:
        base["lorentzian"] = {
            "lrce": lrce,
            "drift": drift,
            "gradient_signed": 0.002,
            "rescue_eligible": rescue_eligible,
            "e_norm": 0.97,
            "confidence_adj": 0.03,
            "quality_band": "STABLE",
            "field_phase": "STABILIZATION",
        }
    return base


def _upstream_pass() -> dict:
    return {"valid": True, "continuation_allowed": True}


def _upstream_fail() -> dict:
    return {"valid": False, "continuation_allowed": False}


# ═══════════════════════════════════════════════════════════════════════════
# §1  Degraded LFS should NOT rescue
# ═══════════════════════════════════════════════════════════════════════════


class TestLFSNeverRescueBadData:
    """All these tests have ENABLE_L8_LFS_RESCUE=True but bad conditions."""

    @patch("analysis.layers.L8_constitutional._ENABLE_L8_LFS_RESCUE", True)
    def test_no_lorentzian_data_no_rescue(self):
        """Missing lorentzian dict → no rescue."""
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(
            _l8_borderline(has_lorentzian=False),
            upstream_output=_upstream_pass(),
        )
        assert result["status"] == L8Status.FAIL.value
        assert "LFS_BORDERLINE_RESCUE" not in result.get("warning_codes", [])

    @patch("analysis.layers.L8_constitutional._ENABLE_L8_LFS_RESCUE", True)
    def test_low_lrce_no_rescue(self):
        """LRCE below threshold → no rescue."""
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(
            _l8_borderline(lrce=0.950),
            upstream_output=_upstream_pass(),
        )
        assert result["status"] == L8Status.FAIL.value
        assert "LFS_BORDERLINE_RESCUE" not in result.get("warning_codes", [])

    @patch("analysis.layers.L8_constitutional._ENABLE_L8_LFS_RESCUE", True)
    def test_high_drift_no_rescue(self):
        """Drift above threshold → no rescue."""
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(
            _l8_borderline(drift=0.010),
            upstream_output=_upstream_pass(),
        )
        assert result["status"] == L8Status.FAIL.value
        assert "LFS_BORDERLINE_RESCUE" not in result.get("warning_codes", [])

    @patch("analysis.layers.L8_constitutional._ENABLE_L8_LFS_RESCUE", True)
    def test_rescue_eligible_false_no_rescue(self):
        """LFS says not rescue_eligible → no rescue."""
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(
            _l8_borderline(rescue_eligible=False),
            upstream_output=_upstream_pass(),
        )
        assert result["status"] == L8Status.FAIL.value
        assert "LFS_BORDERLINE_RESCUE" not in result.get("warning_codes", [])

    @patch("analysis.layers.L8_constitutional._ENABLE_L8_LFS_RESCUE", True)
    def test_upstream_fail_no_rescue(self):
        """Upstream not continuable → blocker → no rescue possible."""
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(
            _l8_borderline(),
            upstream_output=_upstream_fail(),
        )
        assert result["status"] == L8Status.FAIL.value
        assert result["continuation_allowed"] is False

    @patch("analysis.layers.L8_constitutional._ENABLE_L8_LFS_RESCUE", True)
    def test_score_too_low_no_rescue(self):
        """Score far below borderline window → no rescue."""
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(
            _l8_borderline(integrity=0.50),
            upstream_output=_upstream_pass(),
        )
        assert result["status"] == L8Status.FAIL.value
        assert "LFS_BORDERLINE_RESCUE" not in result.get("warning_codes", [])

    @patch("analysis.layers.L8_constitutional._ENABLE_L8_LFS_RESCUE", True)
    def test_score_above_window_not_rescued(self):
        """Score at 0.75 is MID band (WARN already) — rescue not needed."""
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(
            _l8_borderline(integrity=0.78),
            upstream_output=_upstream_pass(),
        )
        # Score 0.78 is MID band → already WARN, no rescue needed
        assert result["status"] in (L8Status.WARN.value, L8Status.PASS.value)

    @patch("analysis.layers.L8_constitutional._ENABLE_L8_LFS_RESCUE", True)
    def test_contract_malformed_no_rescue(self):
        """Invalid l8_analysis dict triggers contract blocker → FAIL."""
        gov = L8ConstitutionalGovernor()
        # Missing required keys
        result = gov.evaluate(
            {"symbol": "EURUSD"},
            upstream_output=_upstream_pass(),
        )
        assert result["status"] == L8Status.FAIL.value
        assert result["continuation_allowed"] is False
