"""Tests for L2 Constitutional Governor — frozen spec v1."""

from __future__ import annotations

from analysis.layers.L2_constitutional import (
    BlockerCode,
    CoherenceBand,
    FallbackClass,
    FreshnessState,
    L2ConstitutionalGovernor,
    L2Status,
    WarmupState,
    _band_from_score,
    _check_critical_blockers,
    _check_upstream_legality,
    _collect_warning_codes,
    _compress_status,
    _eval_fallback,
    _eval_freshness,
    _eval_warmup,
)

# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _l1_pass() -> dict:
    return {"valid": True, "continuation_allowed": True, "status": "PASS"}


def _l1_fail() -> dict:
    return {"valid": False, "continuation_allowed": False, "status": "FAIL"}


def _l2_analysis(
    *,
    valid: bool = True,
    alignment_strength: float = 0.90,
    hierarchy_followed: bool = True,
    aligned: bool = True,
    available_timeframes: int = 4,
    per_tf_bias: dict | None = None,
) -> dict:
    if per_tf_bias is None:
        per_tf_bias = {
            "D1": {"p_bull": 0.7},
            "H4": {"p_bull": 0.65},
            "H1": {"p_bull": 0.6},
            "W1": {"p_bull": 0.72},
        }
    return {
        "valid": valid,
        "alignment_strength": alignment_strength,
        "hierarchy_followed": hierarchy_followed,
        "aligned": aligned,
        "available_timeframes": available_timeframes,
        "per_tf_bias": per_tf_bias,
    }


# ═══════════════════════════════════════════════════════════════════
# §1  Band thresholds (frozen)
# ═══════════════════════════════════════════════════════════════════


class TestBandThresholds:
    def test_high_band(self):
        assert _band_from_score(0.85) == CoherenceBand.HIGH
        assert _band_from_score(1.0) == CoherenceBand.HIGH

    def test_mid_band(self):
        assert _band_from_score(0.65) == CoherenceBand.MID
        assert _band_from_score(0.84) == CoherenceBand.MID

    def test_low_band(self):
        assert _band_from_score(0.64) == CoherenceBand.LOW
        assert _band_from_score(0.0) == CoherenceBand.LOW


# ═══════════════════════════════════════════════════════════════════
# §2  Upstream legality gate
# ═══════════════════════════════════════════════════════════════════


class TestUpstreamLegality:
    def test_pass_when_l1_allows_continuation(self):
        assert _check_upstream_legality(_l1_pass()) == []

    def test_fail_when_l1_blocks(self):
        result = _check_upstream_legality(_l1_fail())
        assert BlockerCode.UPSTREAM_L1_NOT_CONTINUABLE in result

    def test_fail_when_l1_is_not_dict(self):
        result = _check_upstream_legality(None)  # type: ignore[arg-type]
        assert BlockerCode.UPSTREAM_L1_NOT_CONTINUABLE in result

    def test_backward_compat_uses_valid_key(self):
        # Old L1 output without continuation_allowed
        assert _check_upstream_legality({"valid": True}) == []
        result = _check_upstream_legality({"valid": False})
        assert BlockerCode.UPSTREAM_L1_NOT_CONTINUABLE in result


# ═══════════════════════════════════════════════════════════════════
# §3  Critical blockers
# ═══════════════════════════════════════════════════════════════════


class TestCriticalBlockers:
    def test_no_blockers_when_all_ok(self):
        analysis = _l2_analysis()
        tfs = ["D1", "H4", "H1", "W1"]
        assert _check_critical_blockers(analysis, tfs) == []

    def test_required_timeframe_missing(self):
        analysis = _l2_analysis()
        tfs = ["H4", "H1", "W1"]  # D1 missing
        result = _check_critical_blockers(analysis, tfs)
        assert BlockerCode.REQUIRED_TIMEFRAME_MISSING in result

    def test_insufficient_timeframes(self):
        analysis = _l2_analysis(per_tf_bias={"D1": {}, "H4": {}})
        tfs = ["D1", "H4"]  # Only 2, need 3
        result = _check_critical_blockers(analysis, tfs)
        assert BlockerCode.TIMEFRAME_SET_INSUFFICIENT in result

    def test_hierarchy_violated(self):
        analysis = _l2_analysis(hierarchy_followed=False)
        tfs = ["D1", "H4", "H1"]
        result = _check_critical_blockers(analysis, tfs)
        assert BlockerCode.MTA_HIERARCHY_VIOLATED in result

    def test_malformed_payload(self):
        result = _check_critical_blockers({}, [])
        assert BlockerCode.CONTRACT_PAYLOAD_MALFORMED in result


# ═══════════════════════════════════════════════════════════════════
# §4  Freshness gate
# ═══════════════════════════════════════════════════════════════════


class TestFreshness:
    def test_fresh_candle(self):
        assert _eval_freshness({}, 100.0) == FreshnessState.FRESH

    def test_stale_preserved(self):
        assert _eval_freshness({}, 4000.0) == FreshnessState.STALE_PRESERVED

    def test_degraded(self):
        assert _eval_freshness({}, 8000.0) == FreshnessState.DEGRADED

    def test_no_producer_when_invalid(self):
        assert _eval_freshness({"valid": False}, None) == FreshnessState.NO_PRODUCER

    def test_fresh_by_default(self):
        assert _eval_freshness({"valid": True}, None) == FreshnessState.FRESH


# ═══════════════════════════════════════════════════════════════════
# §5  Warmup gate
# ═══════════════════════════════════════════════════════════════════


class TestWarmup:
    def test_ready_with_sufficient_bars(self):
        counts = {"H1": 30, "H4": 15, "D1": 10, "W1": 5, "MN": 2}
        assert _eval_warmup(["D1", "H4", "H1"], counts) == WarmupState.READY

    def test_insufficient_when_required_tf_short(self):
        counts = {"H1": 30, "H4": 2, "D1": 10}  # H4 < 10
        assert _eval_warmup(["D1", "H4", "H1"], counts) == WarmupState.INSUFFICIENT

    def test_partial_when_optional_tf_short(self):
        counts = {"H1": 30, "H4": 15, "D1": 10, "W1": 1}  # W1 < 3
        assert _eval_warmup(["D1", "H4", "H1", "W1"], counts) == WarmupState.PARTIAL

    def test_ready_without_counts(self):
        assert _eval_warmup(["D1", "H4", "H1"], None) == WarmupState.READY

    def test_insufficient_without_counts_no_tfs(self):
        assert _eval_warmup([], None) == WarmupState.INSUFFICIENT


# ═══════════════════════════════════════════════════════════════════
# §6  Fallback gate
# ═══════════════════════════════════════════════════════════════════


class TestFallback:
    def test_no_fallback(self):
        assert _eval_fallback(False, "", False) == FallbackClass.NO_FALLBACK

    def test_legal_primary_substitute(self):
        result = _eval_fallback(True, "substitute_timeframe", True)
        assert result == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE

    def test_legal_emergency_preserve(self):
        result = _eval_fallback(True, "preserved_structure_snapshot", True)
        assert result == FallbackClass.LEGAL_EMERGENCY_PRESERVE

    def test_illegal_when_not_approved(self):
        result = _eval_fallback(True, "whatever", False)
        assert result == FallbackClass.ILLEGAL_FALLBACK


# ═══════════════════════════════════════════════════════════════════
# §7  Compression logic
# ═══════════════════════════════════════════════════════════════════


class TestCompression:
    def test_pass_envelope(self):
        status = _compress_status(
            blockers=[],
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            band=CoherenceBand.HIGH,
            hierarchy_followed=True,
            aligned=True,
            partial_coverage=False,
        )
        assert status == L2Status.PASS

    def test_warn_on_stale_preserved(self):
        status = _compress_status(
            blockers=[],
            freshness=FreshnessState.STALE_PRESERVED,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            band=CoherenceBand.MID,
            hierarchy_followed=True,
            aligned=True,
            partial_coverage=False,
        )
        assert status == L2Status.WARN

    def test_warn_on_partial_coverage(self):
        status = _compress_status(
            blockers=[],
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            band=CoherenceBand.HIGH,
            hierarchy_followed=True,
            aligned=True,
            partial_coverage=True,
        )
        assert status == L2Status.WARN

    def test_fail_on_blocker(self):
        status = _compress_status(
            blockers=["REQUIRED_TIMEFRAME_MISSING"],
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            band=CoherenceBand.HIGH,
            hierarchy_followed=True,
            aligned=True,
            partial_coverage=False,
        )
        assert status == L2Status.FAIL

    def test_fail_on_low_band(self):
        status = _compress_status(
            blockers=[],
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            band=CoherenceBand.LOW,
            hierarchy_followed=True,
            aligned=True,
            partial_coverage=False,
        )
        assert status == L2Status.FAIL

    def test_fail_when_hierarchy_violated_and_no_blocker(self):
        # hierarchy_followed=False doesn't produce a blocker in compression,
        # but WARN envelope requires hierarchy_followed=True
        status = _compress_status(
            blockers=[],
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            band=CoherenceBand.HIGH,
            hierarchy_followed=False,
            aligned=True,
            partial_coverage=False,
        )
        assert status == L2Status.FAIL

    def test_warn_emergency_preserve_with_partial_warmup(self):
        status = _compress_status(
            blockers=[],
            freshness=FreshnessState.STALE_PRESERVED,
            warmup=WarmupState.PARTIAL,
            fallback=FallbackClass.LEGAL_EMERGENCY_PRESERVE,
            band=CoherenceBand.MID,
            hierarchy_followed=True,
            aligned=False,
            partial_coverage=True,
        )
        assert status == L2Status.WARN


# ═══════════════════════════════════════════════════════════════════
# §8  Warning code collection
# ═══════════════════════════════════════════════════════════════════


class TestWarningCodes:
    def test_collects_multiple_warnings(self):
        codes = _collect_warning_codes(
            FreshnessState.STALE_PRESERVED,
            WarmupState.PARTIAL,
            FallbackClass.LEGAL_EMERGENCY_PRESERVE,
            aligned=False,
            partial_coverage=True,
        )
        assert "STRUCTURE_NOT_FULLY_ALIGNED" in codes
        assert "PARTIAL_TIMEFRAME_COVERAGE" in codes
        assert "STALE_PRESERVED_STRUCTURE" in codes
        assert "PARTIAL_WARMUP" in codes
        assert "EMERGENCY_PRESERVE_FALLBACK" in codes

    def test_empty_on_clean_state(self):
        codes = _collect_warning_codes(
            FreshnessState.FRESH,
            WarmupState.READY,
            FallbackClass.NO_FALLBACK,
            aligned=True,
            partial_coverage=False,
        )
        assert codes == []


# ═══════════════════════════════════════════════════════════════════
# §9  Full governor integration
# ═══════════════════════════════════════════════════════════════════


class TestL2ConstitutionalGovernor:
    def setup_method(self):
        self.gov = L2ConstitutionalGovernor()

    def test_pass_envelope_full(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(
                alignment_strength=0.90,
                per_tf_bias={"MN": {}, "W1": {}, "D1": {}, "H4": {}, "H1": {}, "M15": {}},
            ),
            symbol="EURUSD",
        )
        assert result["status"] == "PASS"
        assert result["continuation_allowed"] is True
        assert result["routing"]["next_legal_targets"] == ["L3"]
        assert result["blocker_codes"] == []
        assert result["layer"] == "L2"
        assert result["layer_version"] == "1.0.0"

    def test_fail_when_l1_blocks(self):
        result = self.gov.evaluate(
            l1_output=_l1_fail(),
            l2_analysis=_l2_analysis(),
            symbol="EURUSD",
        )
        assert result["status"] == "FAIL"
        assert result["continuation_allowed"] is False
        assert "UPSTREAM_L1_NOT_CONTINUABLE" in result["blocker_codes"]

    def test_fail_when_required_tf_missing(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(
                per_tf_bias={"H4": {}, "H1": {}, "W1": {}},  # D1 missing
            ),
            symbol="EURUSD",
        )
        assert result["status"] == "FAIL"
        assert "REQUIRED_TIMEFRAME_MISSING" in result["blocker_codes"]

    def test_fail_on_low_alignment(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(alignment_strength=0.50),
            symbol="EURUSD",
        )
        assert result["status"] == "FAIL"
        assert result["continuation_allowed"] is False
        assert result["coherence_band"] == "LOW"

    def test_warn_on_stale_preserved(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(alignment_strength=0.78),
            symbol="EURUSD",
            candle_age_seconds=4000.0,
        )
        assert result["status"] == "WARN"
        assert result["continuation_allowed"] is True
        assert "STALE_PRESERVED_STRUCTURE" in result["warning_codes"]
        # Partial coverage because not all 6 TFs are present
        assert "PARTIAL_TIMEFRAME_COVERAGE" in result["warning_codes"]

    def test_warn_on_partial_warmup(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(alignment_strength=0.78),
            symbol="EURUSD",
            candle_counts={"H1": 30, "H4": 15, "D1": 10, "W1": 1},
        )
        assert result["status"] == "WARN"
        assert result["continuation_allowed"] is True
        assert "PARTIAL_WARMUP" in result["warning_codes"]

    def test_fail_on_illegal_fallback(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(),
            symbol="EURUSD",
            fallback_used=True,
            fallback_source="random_source",
            fallback_approved=False,
        )
        assert result["status"] == "FAIL"
        assert "FALLBACK_DECLARED_BUT_NOT_ALLOWED" in result["blocker_codes"]

    def test_output_contract_has_all_fields(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(),
            symbol="EURUSD",
        )
        required_keys = {
            "layer",
            "layer_version",
            "timestamp",
            "input_ref",
            "status",
            "continuation_allowed",
            "blocker_codes",
            "warning_codes",
            "fallback_class",
            "freshness_state",
            "warmup_state",
            "coherence_band",
            "coherence_score",
            "features",
            "routing",
            "audit",
        }
        assert required_keys.issubset(set(result.keys()))

    def test_features_contain_alignment_score(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(alignment_strength=0.88),
            symbol="EURUSD",
        )
        assert result["features"]["alignment_score"] == 0.88

    def test_features_include_candle_age_evidence(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis() | {"candle_age_by_tf": {"D1": 400000.0, "H4": 1000.0, "H1": 300.0}},
            symbol="EURUSD",
            candle_age_seconds=400000.0,
            candle_counts={"D1": 6, "H4": 12, "H1": 30},
        )
        assert result["features"]["candle_age_seconds"] == 400000.0
        assert result["features"]["candle_age_by_tf"]["D1"] == 400000.0
        assert result["features"]["candle_counts"]["D1"] == 6

    def test_coherence_score_equals_alignment_score(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(alignment_strength=0.77),
            symbol="EURUSD",
        )
        assert result["coherence_score"] == result["features"]["alignment_score"]

    def test_audit_tracks_rule_hits(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(),
            symbol="EURUSD",
        )
        assert len(result["audit"]["rule_hits"]) > 0

    def test_fail_on_hierarchy_violation(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(hierarchy_followed=False),
            symbol="EURUSD",
        )
        assert result["status"] == "FAIL"
        assert "MTA_HIERARCHY_VIOLATED" in result["blocker_codes"]

    def test_pass_with_primary_substitute_fallback(self):
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(
                alignment_strength=0.90,
                per_tf_bias={"MN": {}, "W1": {}, "D1": {}, "H4": {}, "H1": {}, "M15": {}},
            ),
            symbol="EURUSD",
            fallback_used=True,
            fallback_source="substitute_timeframe",
            fallback_approved=True,
        )
        # PASS allowed with LEGAL_PRIMARY_SUBSTITUTE
        assert result["status"] == "PASS"
        assert "PRIMARY_SUBSTITUTE_USED" in result["warning_codes"]

    def test_backward_compat_valid_key_maps_to_continuation(self):
        """L2 constitutional output includes both 'valid' mapping via status."""
        result = self.gov.evaluate(
            l1_output=_l1_pass(),
            l2_analysis=_l2_analysis(),
            symbol="EURUSD",
        )
        # continuation_allowed maps to the old valid behavior
        assert result["continuation_allowed"] is True
