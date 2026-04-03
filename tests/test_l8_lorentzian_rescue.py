"""Tests for L8 LFS borderline rescue — happy path.

Verifies:
- Borderline healthy case (score=0.738, FRESH, READY, strong LFS metrics)
  → status=WARN, continuation_allowed=True, "LFS_BORDERLINE_RESCUE" in warning_codes
- Requires ENABLE_L8_LFS_RESCUE feature flag
"""

from __future__ import annotations

from unittest.mock import patch

from analysis.layers.L8_constitutional import (
    L8BlockerCode,
    L8ConstitutionalGovernor,
    L8FallbackClass,
    L8FreshnessState,
    L8Status,
    L8WarmupState,
    _can_apply_lfs_borderline_rescue,
)

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _l8_borderline_healthy(
    *,
    integrity: float = 0.738,
    lrce: float = 0.972,
    drift: float = 0.0039,
    gradient_signed: float = 0.002,
    rescue_eligible: bool = True,
) -> dict:
    """L8 analysis payload at borderline integrity with strong LFS metrics."""
    return {
        "tii_sym": 0.80,
        "tii_status": "ACCEPTABLE",
        "tii_grade": "ACCEPTABLE",
        "integrity": integrity,
        "twms_score": 0.70,
        "gate_status": "OPEN",
        "gate_passed": True,
        "valid": True,
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
        "lorentzian": {
            "lrce": lrce,
            "drift": drift,
            "gradient_signed": gradient_signed,
            "rescue_eligible": rescue_eligible,
            "e_norm": 0.97,
            "confidence_adj": 0.03,
            "quality_band": "STABLE",
            "field_phase": "STABILIZATION",
        },
    }


def _upstream_pass() -> dict:
    return {"valid": True, "continuation_allowed": True}


# ═══════════════════════════════════════════════════════════════════════════
# §1  _can_apply_lfs_borderline_rescue — Unit Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestCanApplyLFSBorderlineRescue:
    def test_happy_path(self):
        result = _can_apply_lfs_borderline_rescue(
            _l8_borderline_healthy(),
            integrity_score=0.738,
            freshness=L8FreshnessState.FRESH,
            warmup=L8WarmupState.READY,
            fallback=L8FallbackClass.NO_FALLBACK,
            blockers=[],
        )
        assert result is True

    def test_hard_blockers_prevent_rescue(self):
        """Hard blockers (anything other than INTEGRITY_SCORE_BELOW_MINIMUM) prevent rescue."""
        result = _can_apply_lfs_borderline_rescue(
            _l8_borderline_healthy(),
            integrity_score=0.738,
            freshness=L8FreshnessState.FRESH,
            warmup=L8WarmupState.READY,
            fallback=L8FallbackClass.NO_FALLBACK,
            blockers=[L8BlockerCode.TII_UNAVAILABLE],
        )
        assert result is False

    def test_integrity_blocker_allowed_for_rescue(self):
        """INTEGRITY_SCORE_BELOW_MINIMUM alone does NOT block rescue — it's what rescue is for."""
        result = _can_apply_lfs_borderline_rescue(
            _l8_borderline_healthy(),
            integrity_score=0.738,
            freshness=L8FreshnessState.FRESH,
            warmup=L8WarmupState.READY,
            fallback=L8FallbackClass.NO_FALLBACK,
            blockers=[L8BlockerCode.INTEGRITY_SCORE_BELOW_MINIMUM],
        )
        assert result is True

    def test_stale_prevents_rescue(self):
        result = _can_apply_lfs_borderline_rescue(
            _l8_borderline_healthy(),
            integrity_score=0.738,
            freshness=L8FreshnessState.STALE_PRESERVED,
            warmup=L8WarmupState.READY,
            fallback=L8FallbackClass.NO_FALLBACK,
            blockers=[],
        )
        assert result is False

    def test_insufficient_warmup_prevents_rescue(self):
        result = _can_apply_lfs_borderline_rescue(
            _l8_borderline_healthy(),
            integrity_score=0.738,
            freshness=L8FreshnessState.FRESH,
            warmup=L8WarmupState.INSUFFICIENT,
            fallback=L8FallbackClass.NO_FALLBACK,
            blockers=[],
        )
        assert result is False

    def test_illegal_fallback_prevents_rescue(self):
        result = _can_apply_lfs_borderline_rescue(
            _l8_borderline_healthy(),
            integrity_score=0.738,
            freshness=L8FreshnessState.FRESH,
            warmup=L8WarmupState.READY,
            fallback=L8FallbackClass.ILLEGAL_FALLBACK,
            blockers=[],
        )
        assert result is False

    def test_score_below_window(self):
        result = _can_apply_lfs_borderline_rescue(
            _l8_borderline_healthy(),
            integrity_score=0.71,  # below 0.72
            freshness=L8FreshnessState.FRESH,
            warmup=L8WarmupState.READY,
            fallback=L8FallbackClass.NO_FALLBACK,
            blockers=[],
        )
        assert result is False

    def test_score_above_window(self):
        result = _can_apply_lfs_borderline_rescue(
            _l8_borderline_healthy(),
            integrity_score=0.76,  # above 0.75
            freshness=L8FreshnessState.FRESH,
            warmup=L8WarmupState.READY,
            fallback=L8FallbackClass.NO_FALLBACK,
            blockers=[],
        )
        assert result is False

    def test_low_lrce_prevents_rescue(self):
        result = _can_apply_lfs_borderline_rescue(
            _l8_borderline_healthy(lrce=0.960),
            integrity_score=0.738,
            freshness=L8FreshnessState.FRESH,
            warmup=L8WarmupState.READY,
            fallback=L8FallbackClass.NO_FALLBACK,
            blockers=[],
        )
        assert result is False

    def test_high_drift_prevents_rescue(self):
        result = _can_apply_lfs_borderline_rescue(
            _l8_borderline_healthy(drift=0.006),
            integrity_score=0.738,
            freshness=L8FreshnessState.FRESH,
            warmup=L8WarmupState.READY,
            fallback=L8FallbackClass.NO_FALLBACK,
            blockers=[],
        )
        assert result is False

    def test_not_rescue_eligible_prevents_rescue(self):
        result = _can_apply_lfs_borderline_rescue(
            _l8_borderline_healthy(rescue_eligible=False),
            integrity_score=0.738,
            freshness=L8FreshnessState.FRESH,
            warmup=L8WarmupState.READY,
            fallback=L8FallbackClass.NO_FALLBACK,
            blockers=[],
        )
        assert result is False

    def test_no_lorentzian_key_prevents_rescue(self):
        analysis = _l8_borderline_healthy()
        del analysis["lorentzian"]
        result = _can_apply_lfs_borderline_rescue(
            analysis,
            integrity_score=0.738,
            freshness=L8FreshnessState.FRESH,
            warmup=L8WarmupState.READY,
            fallback=L8FallbackClass.NO_FALLBACK,
            blockers=[],
        )
        assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# §2  Full Governor — L8 Rescue Integration
# ═══════════════════════════════════════════════════════════════════════════


class TestL8GovernorRescue:
    """Test full evaluate() with LFS rescue enabled."""

    @patch("analysis.layers.L8_constitutional._ENABLE_L8_LFS_RESCUE", True)
    def test_borderline_rescue_promotes_to_warn(self):
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(
            _l8_borderline_healthy(integrity=0.738),
            upstream_output=_upstream_pass(),
        )
        assert result["status"] == L8Status.WARN.value
        assert result["continuation_allowed"] is True
        assert "LFS_BORDERLINE_RESCUE" in result["warning_codes"]
        assert result["routing"]["next_legal_targets"] == ["L9"]

    @patch("analysis.layers.L8_constitutional._ENABLE_L8_LFS_RESCUE", True)
    def test_rescue_note_present(self):
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(
            _l8_borderline_healthy(integrity=0.738),
            upstream_output=_upstream_pass(),
        )
        notes = result.get("audit", {}).get("notes", [])
        assert any("LFS rescue" in n for n in notes)

    @patch("analysis.layers.L8_constitutional._ENABLE_L8_LFS_RESCUE", False)
    def test_rescue_disabled_remains_fail(self):
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(
            _l8_borderline_healthy(integrity=0.738),
            upstream_output=_upstream_pass(),
        )
        assert result["status"] == L8Status.FAIL.value
        assert result["continuation_allowed"] is False
        assert "LFS_BORDERLINE_RESCUE" not in result.get("warning_codes", [])
