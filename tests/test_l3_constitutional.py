"""Tests for L3 Constitutional Governor — frozen spec v1.0.0."""

from __future__ import annotations

import pytest

from analysis.layers.L3_constitutional import (
    BlockerCode,
    CoherenceBand,
    FallbackClass,
    FreshnessState,
    L3ConstitutionalGovernor,
    L3Status,
    WarmupState,
    _band_from_score,
    _check_critical_blockers,
    _check_structure_conflict,
    _check_upstream_legality,
    _collect_warning_codes,
    _compress_status,
    _compute_confirmation_score,
    _eval_fallback,
    _eval_freshness,
    _eval_warmup,
)

# ── Helpers ───────────────────────────────────────────────────


def _healthy_l2() -> dict:
    return {"valid": True, "continuation_allowed": True, "status": "PASS"}


def _healthy_l3() -> dict:
    return {
        "valid": True,
        "trend": "BULLISH",
        "technical_score": 65,
        "edge_probability": 0.88,
        "trend_strength": 0.75,
        "structure_validity": "STRONG",
        "confidence": 3,
        "trq3d_energy": 0.45,
        "adx": 35.0,
        "data_quality": "HEALTHY",
        "fvg_detected": False,
        "ob_detected": False,
    }


# ═══════════════════════════════════════════════════════════════
# §1  Band thresholds
# ═══════════════════════════════════════════════════════════════


class TestBandFromScore:
    def test_high(self):
        assert _band_from_score(0.90) == CoherenceBand.HIGH

    def test_mid(self):
        assert _band_from_score(0.40) == CoherenceBand.MID

    def test_low(self):
        assert _band_from_score(0.20) == CoherenceBand.LOW

    def test_boundary_high(self):
        assert _band_from_score(0.55) == CoherenceBand.HIGH

    def test_boundary_mid(self):
        assert _band_from_score(0.25) == CoherenceBand.MID

    def test_below_boundary_mid(self):
        assert _band_from_score(0.2499) == CoherenceBand.LOW


# ═══════════════════════════════════════════════════════════════
# §2  Upstream legality
# ═══════════════════════════════════════════════════════════════


class TestUpstreamLegality:
    def test_pass_with_continuation(self):
        assert _check_upstream_legality({"continuation_allowed": True}) == []

    def test_fail_with_no_continuation(self):
        result = _check_upstream_legality({"continuation_allowed": False})
        assert BlockerCode.UPSTREAM_L2_NOT_CONTINUABLE in result

    def test_backward_compat_valid(self):
        assert _check_upstream_legality({"valid": True}) == []

    def test_fail_not_dict(self):
        result = _check_upstream_legality("invalid")  # type: ignore[arg-type]
        assert BlockerCode.UPSTREAM_L2_NOT_CONTINUABLE in result


# ═══════════════════════════════════════════════════════════════
# §3  Critical blockers
# ═══════════════════════════════════════════════════════════════


class TestCriticalBlockers:
    def test_pass_healthy(self):
        assert _check_critical_blockers(_healthy_l3()) == []

    def test_fail_malformed(self):
        result = _check_critical_blockers({})
        assert BlockerCode.CONTRACT_PAYLOAD_MALFORMED in result

    def test_fail_not_dict(self):
        result = _check_critical_blockers("bad")  # type: ignore[arg-type]
        assert BlockerCode.CONTRACT_PAYLOAD_MALFORMED in result

    def test_fail_neutral_low_score(self):
        l3 = _healthy_l3()
        l3["trend"] = "NEUTRAL"
        l3["technical_score"] = 10
        result = _check_critical_blockers(l3)
        assert BlockerCode.TREND_CONFIRMATION_UNAVAILABLE in result

    def test_pass_neutral_decent_score(self):
        l3 = _healthy_l3()
        l3["trend"] = "NEUTRAL"
        l3["technical_score"] = 20
        assert _check_critical_blockers(l3) == []


# ═══════════════════════════════════════════════════════════════
# §4  Freshness
# ═══════════════════════════════════════════════════════════════


class TestFreshness:
    def test_fresh_from_age(self):
        assert _eval_freshness({}, 100.0) == FreshnessState.FRESH

    def test_stale_from_age(self):
        assert _eval_freshness({}, 4000.0) == FreshnessState.STALE_PRESERVED

    def test_degraded_from_age(self):
        assert _eval_freshness({}, 8000.0) == FreshnessState.DEGRADED

    def test_degraded_from_flat_data(self):
        assert _eval_freshness({"data_quality": "FLAT"}, None) == FreshnessState.DEGRADED

    def test_stale_from_stale_close(self):
        assert _eval_freshness({"data_quality": "STALE_CLOSE"}, None) == FreshnessState.STALE_PRESERVED

    def test_fresh_from_valid(self):
        assert _eval_freshness({"valid": True}, None) == FreshnessState.FRESH

    def test_degraded_from_invalid(self):
        assert _eval_freshness({"valid": False}, None) == FreshnessState.DEGRADED


# ═══════════════════════════════════════════════════════════════
# §5  Warmup
# ═══════════════════════════════════════════════════════════════


class TestWarmup:
    def test_ready_from_count(self):
        assert _eval_warmup({}, 50) == WarmupState.READY

    def test_partial_from_count(self):
        assert _eval_warmup({}, 25) == WarmupState.PARTIAL

    def test_insufficient_from_count(self):
        assert _eval_warmup({}, 10) == WarmupState.INSUFFICIENT

    def test_ready_from_valid_l3(self):
        assert _eval_warmup({"valid": True}, None) == WarmupState.READY

    def test_insufficient_from_invalid_l3(self):
        assert _eval_warmup({"valid": False}, None) == WarmupState.INSUFFICIENT


# ═══════════════════════════════════════════════════════════════
# §6  Fallback
# ═══════════════════════════════════════════════════════════════


class TestFallback:
    def test_no_fallback(self):
        assert _eval_fallback(False, "", False) == FallbackClass.NO_FALLBACK

    def test_illegal(self):
        assert _eval_fallback(True, "unknown", False) == FallbackClass.ILLEGAL_FALLBACK

    def test_primary_substitute(self):
        assert _eval_fallback(True, "substitute_trend_source", True) == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE

    def test_emergency_preserve(self):
        assert _eval_fallback(True, "hl_midpoint_synthetic", True) == FallbackClass.LEGAL_EMERGENCY_PRESERVE


# ═══════════════════════════════════════════════════════════════
# §7  Confirmation score
# ═══════════════════════════════════════════════════════════════


class TestConfirmationScore:
    def test_from_edge_probability(self):
        assert _compute_confirmation_score({"edge_probability": 0.82}) == pytest.approx(0.82)

    def test_from_tech_score(self):
        assert _compute_confirmation_score({"technical_score": 70}) == pytest.approx(0.70)

    def test_zero_fallback(self):
        assert _compute_confirmation_score({}) == 0.0


# ═══════════════════════════════════════════════════════════════
# §8  Structure conflict
# ═══════════════════════════════════════════════════════════════


class TestStructureConflict:
    def test_no_conflict_healthy(self):
        assert _check_structure_conflict(_healthy_l3()) is False

    def test_no_conflict_flat_data(self):
        """FLAT data quality is handled by freshness gate, not structure conflict."""
        l3 = _healthy_l3()
        l3["data_quality"] = "FLAT"
        assert _check_structure_conflict(l3) is False

    def test_conflict_weak_directional(self):
        l3 = _healthy_l3()
        l3["structure_validity"] = "WEAK"
        l3["confidence"] = 1
        assert _check_structure_conflict(l3) is True

    def test_no_conflict_neutral(self):
        l3 = _healthy_l3()
        l3["trend"] = "NEUTRAL"
        l3["structure_validity"] = "WEAK"
        l3["confidence"] = 1
        assert _check_structure_conflict(l3) is False


# ═══════════════════════════════════════════════════════════════
# §9  Compression logic
# ═══════════════════════════════════════════════════════════════


class TestCompression:
    def test_fail_with_blockers(self):
        assert (
            _compress_status(
                ["X"],
                FreshnessState.FRESH,
                WarmupState.READY,
                FallbackClass.NO_FALLBACK,
                CoherenceBand.HIGH,
                True,
                False,
                True,
            )
            == L3Status.FAIL
        )

    def test_warn_low_band_in_warn_range(self):
        """LOW band without blockers = score in WARN range (above hard floor)."""
        assert (
            _compress_status(
                [],
                FreshnessState.FRESH,
                WarmupState.READY,
                FallbackClass.NO_FALLBACK,
                CoherenceBand.LOW,
                True,
                False,
                True,
            )
            == L3Status.WARN
        )

    def test_fail_not_confirmed(self):
        assert (
            _compress_status(
                [],
                FreshnessState.FRESH,
                WarmupState.READY,
                FallbackClass.NO_FALLBACK,
                CoherenceBand.HIGH,
                False,
                False,
                True,
            )
            == L3Status.FAIL
        )

    def test_fail_structure_conflict(self):
        assert (
            _compress_status(
                [],
                FreshnessState.FRESH,
                WarmupState.READY,
                FallbackClass.NO_FALLBACK,
                CoherenceBand.HIGH,
                True,
                True,
                True,
            )
            == L3Status.FAIL
        )

    def test_pass_clean(self):
        assert (
            _compress_status(
                [],
                FreshnessState.FRESH,
                WarmupState.READY,
                FallbackClass.NO_FALLBACK,
                CoherenceBand.HIGH,
                True,
                False,
                True,
            )
            == L3Status.PASS
        )

    def test_pass_with_primary_substitute(self):
        assert (
            _compress_status(
                [],
                FreshnessState.FRESH,
                WarmupState.READY,
                FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
                CoherenceBand.MID,
                True,
                False,
                True,
            )
            == L3Status.PASS
        )

    def test_warn_stale_preserved(self):
        assert (
            _compress_status(
                [],
                FreshnessState.STALE_PRESERVED,
                WarmupState.READY,
                FallbackClass.NO_FALLBACK,
                CoherenceBand.HIGH,
                True,
                False,
                True,
            )
            == L3Status.WARN
        )

    def test_warn_partial_warmup(self):
        assert (
            _compress_status(
                [],
                FreshnessState.FRESH,
                WarmupState.PARTIAL,
                FallbackClass.NO_FALLBACK,
                CoherenceBand.MID,
                True,
                False,
                True,
            )
            == L3Status.WARN
        )

    def test_warn_emergency_preserve(self):
        assert (
            _compress_status(
                [],
                FreshnessState.FRESH,
                WarmupState.READY,
                FallbackClass.LEGAL_EMERGENCY_PRESERVE,
                CoherenceBand.HIGH,
                True,
                False,
                True,
            )
            == L3Status.WARN
        )

    def test_warn_neutral_trend(self):
        """NEUTRAL trend with valid analysis → WARN (not FAIL)."""
        assert (
            _compress_status(
                [],
                FreshnessState.FRESH,
                WarmupState.READY,
                FallbackClass.NO_FALLBACK,
                CoherenceBand.HIGH,
                True,
                False,
                False,
            )
            == L3Status.WARN
        )

    def test_warn_neutral_trend_low_band(self):
        """NEUTRAL trend with LOW band (above hard floor) → WARN."""
        assert (
            _compress_status(
                [],
                FreshnessState.FRESH,
                WarmupState.READY,
                FallbackClass.NO_FALLBACK,
                CoherenceBand.LOW,
                True,
                False,
                False,
            )
            == L3Status.WARN
        )


# ═══════════════════════════════════════════════════════════════
# §10  Warning codes
# ═══════════════════════════════════════════════════════════════


class TestWarningCodes:
    def test_stale_close(self):
        warnings = _collect_warning_codes(
            FreshnessState.FRESH, WarmupState.READY, FallbackClass.NO_FALLBACK, "STALE_CLOSE"
        )
        assert "STALE_CLOSE_DATA" in warnings

    def test_emergency_preserve(self):
        warnings = _collect_warning_codes(
            FreshnessState.FRESH, WarmupState.READY, FallbackClass.LEGAL_EMERGENCY_PRESERVE, "HEALTHY"
        )
        assert "EMERGENCY_PRESERVE_FALLBACK" in warnings

    def test_primary_substitute(self):
        warnings = _collect_warning_codes(
            FreshnessState.FRESH, WarmupState.READY, FallbackClass.LEGAL_PRIMARY_SUBSTITUTE, "HEALTHY"
        )
        assert "PRIMARY_SUBSTITUTE_USED" in warnings


# ═══════════════════════════════════════════════════════════════
# §11  Governor integration tests
# ═══════════════════════════════════════════════════════════════


class TestGovernorIntegration:
    def setup_method(self):
        self.gov = L3ConstitutionalGovernor()

    def test_pass_clean_envelope(self):
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=_healthy_l3(),
            symbol="EURUSD",
        )
        assert result["status"] == "PASS"
        assert result["continuation_allowed"] is True
        assert result["routing"]["next_legal_targets"] == ["L4"]
        assert result["layer"] == "L3"
        assert result["layer_version"] == "1.0.0"
        assert result["coherence_band"] in ("HIGH", "MID")
        assert result["blocker_codes"] == []
        assert result["features"]["trend_confirmed"] is True
        assert result["features"]["structure_conflict"] is False

    def test_fail_upstream_l2_not_continuable(self):
        result = self.gov.evaluate(
            l2_output={"continuation_allowed": False},
            l3_analysis=_healthy_l3(),
            symbol="EURUSD",
        )
        assert result["status"] == "FAIL"
        assert result["continuation_allowed"] is False
        assert BlockerCode.UPSTREAM_L2_NOT_CONTINUABLE.value in result["blocker_codes"]
        assert result["routing"]["next_legal_targets"] == []

    def test_fail_neutral_trend_low_score(self):
        l3 = _healthy_l3()
        l3["trend"] = "NEUTRAL"
        l3["technical_score"] = 10
        l3["edge_probability"] = 0.05
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=l3,
            symbol="GBPUSD",
        )
        assert result["status"] == "FAIL"
        assert result["continuation_allowed"] is False

    def test_warn_stale_close_data(self):
        l3 = _healthy_l3()
        l3["data_quality"] = "STALE_CLOSE"
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=l3,
            symbol="CADCHF",
        )
        # STALE_CLOSE → auto-detects LEGAL_EMERGENCY_PRESERVE fallback → WARN
        assert result["status"] == "WARN"
        assert result["continuation_allowed"] is True
        assert "STALE_CLOSE_DATA" in result["warning_codes"]
        assert result["fallback_class"] == "LEGAL_EMERGENCY_PRESERVE"

    def test_warn_flat_data_valid_analysis(self):
        """FLAT data quality with valid analysis → WARN (degraded but continuable)."""
        l3 = _healthy_l3()
        l3["data_quality"] = "FLAT"
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=l3,
            symbol="NZDUSD",
        )
        assert result["status"] == "WARN"
        assert result["continuation_allowed"] is True
        assert result["freshness_state"] == "DEGRADED"

    def test_fail_malformed_l3(self):
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis={},
            symbol="XAUUSD",
        )
        assert result["status"] == "FAIL"
        assert BlockerCode.CONTRACT_PAYLOAD_MALFORMED.value in result["blocker_codes"]

    def test_pass_with_primary_substitute_fallback(self):
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=_healthy_l3(),
            symbol="EURUSD",
            fallback_used=True,
            fallback_source="substitute_trend_source",
            fallback_approved=True,
        )
        assert result["status"] == "PASS"
        assert "PRIMARY_SUBSTITUTE_USED" in result["warning_codes"]

    def test_warn_degraded_freshness(self):
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=_healthy_l3(),
            symbol="EURUSD",
            candle_age_seconds=5000.0,
        )
        assert result["status"] == "WARN"
        assert "STALE_PRESERVED_TREND" in result["warning_codes"]

    def test_features_include_candle_age_evidence(self):
        l3 = _healthy_l3()
        l3["candle_age_by_tf"] = {"D1": 400000.0, "H4": 15000.0, "H1": 1800.0}
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=l3,
            symbol="EURUSD",
            candle_age_seconds=400000.0,
            h1_bar_count=30,
        )
        assert result["features"]["candle_age_seconds"] == 400000.0
        assert result["features"]["candle_age_by_tf"]["D1"] == 400000.0
        assert result["features"]["h1_bar_count"] == 30

    def test_pass_has_available_sources(self):
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=_healthy_l3(),
            symbol="EURUSD",
        )
        assert "ema_stack" in result["features"]["available_trend_sources"]
        assert "momentum_sync" in result["features"]["available_trend_sources"]
        assert "adx_trending" in result["features"]["available_trend_sources"]

    def test_audit_rule_hits_populated(self):
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=_healthy_l3(),
            symbol="EURUSD",
        )
        assert len(result["audit"]["rule_hits"]) > 0
        assert any("freshness_state" in h for h in result["audit"]["rule_hits"])
        assert any("warmup_state" in h for h in result["audit"]["rule_hits"])

    def test_backward_compat_valid_field(self):
        """L2 output with legacy 'valid' field should still work."""
        result = self.gov.evaluate(
            l2_output={"valid": True},
            l3_analysis=_healthy_l3(),
            symbol="EURUSD",
        )
        assert result["status"] == "PASS"

    def test_fail_insufficient_warmup(self):
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=_healthy_l3(),
            symbol="EURUSD",
            h1_bar_count=10,
        )
        assert result["status"] == "FAIL"
        assert BlockerCode.WARMUP_INSUFFICIENT.value in result["blocker_codes"]

    def test_structure_conflict_directional_weak(self):
        l3 = _healthy_l3()
        l3["structure_validity"] = "WEAK"
        l3["confidence"] = 1
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=l3,
            symbol="GBPUSD",
        )
        assert result["status"] == "FAIL"
        assert BlockerCode.TREND_STRUCTURE_CONFLICT.value in result["blocker_codes"]
        assert result["features"]["structure_conflict"] is True

    def test_warn_neutral_trend_cadchf(self):
        """CADCHF-like: NEUTRAL trend, valid analysis, decent score → WARN."""
        l3 = _healthy_l3()
        l3["trend"] = "NEUTRAL"
        l3["technical_score"] = 21
        l3["edge_probability"] = 0.70
        l3["structure_validity"] = "WEAK"
        l3["confidence"] = 1
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=l3,
            symbol="CADCHF",
        )
        assert result["status"] == "WARN"
        assert result["continuation_allowed"] is True
        assert "NEUTRAL_TREND_NON_DIRECTIONAL" in result["warning_codes"]
        assert result["features"]["trend_confirmed"] is True
        assert result["features"]["structure_conflict"] is False

    def test_fail_low_confirmation_score_has_blocker_code(self):
        """LOW band should produce explicit LOW_CONFIRMATION_SCORE blocker for diagnostics."""
        l3 = _healthy_l3()
        l3["edge_probability"] = 0.10  # Very low → LOW band
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=l3,
            symbol="GBPJPY",
        )
        assert result["status"] == "FAIL"
        assert BlockerCode.LOW_CONFIRMATION_SCORE.value in result["blocker_codes"]
        assert result["continuation_allowed"] is False

    def test_warn_moderate_edge_probability_eurjpy(self):
        """EURJPY-like: directional trend, valid analysis, moderate sigmoid P_edge → WARN.

        With recalibrated thresholds (MID >= 0.25), a moderate P_edge of 0.35
        should produce MID band and WARN status, not FAIL.
        """
        l3 = _healthy_l3()
        l3["edge_probability"] = 0.35  # Moderate sigmoid output
        l3["trend"] = "BULLISH"
        result = self.gov.evaluate(
            l2_output=_healthy_l2(),
            l3_analysis=l3,
            symbol="EURJPY",
        )
        assert result["status"] in ("PASS", "WARN")
        assert result["continuation_allowed"] is True
        assert result["coherence_band"] == "MID"
        assert BlockerCode.LOW_CONFIRMATION_SCORE.value not in result["blocker_codes"]
