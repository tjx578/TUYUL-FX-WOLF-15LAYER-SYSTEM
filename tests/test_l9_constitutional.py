"""Tests for L9 Constitutional Governor — Strict Mode v1.0.0."""

from __future__ import annotations

from analysis.layers.L9_constitutional import (
    L9BlockerCode,
    L9CoherenceBand,
    L9ConstitutionalGovernor,
    L9FallbackClass,
    L9FreshnessState,
    L9Status,
    L9WarmupState,
    _check_contract,
    _check_smc_validation,
    _check_structure_sources,
    _check_upstream,
    _collect_warning_codes,
    _compress_status,
    _derive_structure_score,
    _eval_fallback,
    _eval_freshness,
    _eval_warmup,
    _score_band,
)

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _upstream_pass() -> dict:
    return {"valid": True, "continuation_allowed": True}


def _upstream_fail() -> dict:
    return {"valid": False, "continuation_allowed": False}


def _l9_analysis(
    *,
    smc_score: int = 85,
    liquidity_score: float = 0.75,
    dvg_confidence: float = 0.80,
    smart_money_bias: str = "BULLISH",
    smart_money_signal: str = "ACCUMULATION",
    ob_present: bool = True,
    fvg_present: bool = True,
    sweep_detected: bool = True,
    confidence: float = 0.85,
    valid: bool = True,
    smc: bool = True,
    bos_detected: bool = True,
    choch_detected: bool = False,
    displacement: bool = True,
    liquidity_sweep: bool = True,
    reason: str = "smc_ok",
) -> dict:
    return {
        "smc_score": smc_score,
        "liquidity_score": liquidity_score,
        "dvg_confidence": dvg_confidence,
        "smart_money_bias": smart_money_bias,
        "smart_money_signal": smart_money_signal,
        "ob_present": ob_present,
        "fvg_present": fvg_present,
        "sweep_detected": sweep_detected,
        "confidence": confidence,
        "valid": valid,
        "smc": smc,
        "bos_detected": bos_detected,
        "choch_detected": choch_detected,
        "displacement": displacement,
        "liquidity_sweep": liquidity_sweep,
        "reason": reason,
        "symbol": "EURUSD",
    }


def _l9_fail(reason: str = "no_structure_data") -> dict:
    return {
        "smc_score": 0,
        "liquidity_score": 0.0,
        "dvg_confidence": 0.0,
        "smart_money_bias": "NEUTRAL",
        "smart_money_signal": "NEUTRAL",
        "ob_present": False,
        "fvg_present": False,
        "sweep_detected": False,
        "confidence": 0.0,
        "valid": False,
        "smc": False,
        "bos_detected": False,
        "choch_detected": False,
        "displacement": False,
        "liquidity_sweep": False,
        "reason": reason,
        "symbol": "EURUSD",
    }


# ═══════════════════════════════════════════════════════════════════════════
# §1  Score Band Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestScoreBand:
    def test_high_band(self):
        assert _score_band(0.80) == L9CoherenceBand.HIGH
        assert _score_band(0.95) == L9CoherenceBand.HIGH

    def test_mid_band(self):
        assert _score_band(0.65) == L9CoherenceBand.MID
        assert _score_band(0.79) == L9CoherenceBand.MID

    def test_low_band(self):
        assert _score_band(0.64) == L9CoherenceBand.LOW
        assert _score_band(0.30) == L9CoherenceBand.LOW
        assert _score_band(0.0) == L9CoherenceBand.LOW


# ═══════════════════════════════════════════════════════════════════════════
# §2  Upstream Check Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestUpstreamCheck:
    def test_pass(self):
        assert _check_upstream(_upstream_pass()) == []

    def test_fail(self):
        blockers = _check_upstream(_upstream_fail())
        assert L9BlockerCode.UPSTREAM_NOT_CONTINUABLE in blockers

    def test_empty(self):
        blockers = _check_upstream({})
        assert L9BlockerCode.UPSTREAM_NOT_CONTINUABLE in blockers


# ═══════════════════════════════════════════════════════════════════════════
# §3  Contract Check Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestContractCheck:
    def test_valid(self):
        assert _check_contract(_l9_analysis()) == []

    def test_empty(self):
        blockers = _check_contract({})
        assert L9BlockerCode.CONTRACT_PAYLOAD_MALFORMED in blockers

    def test_minimal_keys(self):
        assert _check_contract({"smc_score": 50}) == []
        assert _check_contract({"valid": True}) == []
        assert _check_contract({"confidence": 0.5}) == []


# ═══════════════════════════════════════════════════════════════════════════
# §4  Structure Source Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStructureSources:
    def test_valid_analysis(self):
        assert _check_structure_sources(_l9_analysis()) == []

    def test_no_structure_data(self):
        data = _l9_fail("no_structure_data")
        blockers = _check_structure_sources(data)
        assert L9BlockerCode.REQUIRED_STRUCTURE_SOURCE_MISSING in blockers

    def test_invalid_structure(self):
        data = _l9_fail("invalid_structure")
        blockers = _check_structure_sources(data)
        assert L9BlockerCode.REQUIRED_STRUCTURE_SOURCE_MISSING in blockers


# ═══════════════════════════════════════════════════════════════════════════
# §5  Freshness Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestFreshness:
    def test_explicit(self):
        data = {**_l9_analysis(), "freshness_state": "STALE_PRESERVED"}
        assert _eval_freshness(data) == L9FreshnessState.STALE_PRESERVED

    def test_no_structure_data(self):
        data = _l9_fail("no_structure_data")
        assert _eval_freshness(data) == L9FreshnessState.NO_PRODUCER

    def test_valid_smc(self):
        assert _eval_freshness(_l9_analysis()) == L9FreshnessState.FRESH

    def test_valid_no_score(self):
        data = {**_l9_analysis(), "smc_score": 0}
        assert _eval_freshness(data) == L9FreshnessState.DEGRADED


# ═══════════════════════════════════════════════════════════════════════════
# §6  Warmup Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestWarmup:
    def test_ready(self):
        assert _eval_warmup(_l9_analysis()) == L9WarmupState.READY

    def test_partial(self):
        data = _l9_analysis(
            bos_detected=True,
            choch_detected=False,
            fvg_present=False,
            ob_present=False,
            sweep_detected=False,
        )
        assert _eval_warmup(data) == L9WarmupState.PARTIAL

    def test_insufficient(self):
        data = _l9_fail()
        assert _eval_warmup(data) == L9WarmupState.INSUFFICIENT

    def test_explicit(self):
        data = {**_l9_analysis(), "warmup_state": "PARTIAL"}
        assert _eval_warmup(data) == L9WarmupState.PARTIAL


# ═══════════════════════════════════════════════════════════════════════════
# §7  Fallback Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestFallback:
    def test_no_fallback(self):
        assert _eval_fallback(_l9_analysis()) == L9FallbackClass.NO_FALLBACK

    def test_no_structure(self):
        data = _l9_fail("no_structure_data")
        assert _eval_fallback(data) == L9FallbackClass.LEGAL_EMERGENCY_PRESERVE

    def test_invalid_structure(self):
        data = _l9_fail("invalid_structure")
        assert _eval_fallback(data) == L9FallbackClass.LEGAL_EMERGENCY_PRESERVE

    def test_explicit(self):
        data = {**_l9_analysis(), "fallback_class": "ILLEGAL_FALLBACK"}
        assert _eval_fallback(data) == L9FallbackClass.ILLEGAL_FALLBACK


# ═══════════════════════════════════════════════════════════════════════════
# §8  SMC Validation Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSMCValidation:
    def test_good_signal(self):
        blockers, warnings = _check_smc_validation(_l9_analysis())
        assert not blockers
        assert "NO_SMC_SIGNAL" not in warnings

    def test_no_smc_signal(self):
        data = _l9_analysis(smc=False)
        _, warnings = _check_smc_validation(data)
        assert "NO_SMC_SIGNAL" in warnings

    def test_zero_confidence(self):
        data = _l9_analysis(confidence=0.0)
        _, warnings = _check_smc_validation(data)
        assert "ZERO_CONFIDENCE" in warnings

    def test_no_divergence(self):
        data = _l9_analysis(dvg_confidence=0.0)
        _, warnings = _check_smc_validation(data)
        assert "NO_DIVERGENCE_DATA" in warnings

    def test_no_liquidity(self):
        data = _l9_analysis(liquidity_score=0.0)
        _, warnings = _check_smc_validation(data)
        assert "NO_LIQUIDITY_DATA" in warnings

    def test_invalid_score_range(self):
        data = _l9_analysis(smc_score=150)
        blockers, _ = _check_smc_validation(data)
        assert L9BlockerCode.INVALID_STRUCTURE_STATE in blockers


# ═══════════════════════════════════════════════════════════════════════════
# §9  Structure Score Derivation
# ═══════════════════════════════════════════════════════════════════════════


class TestStructureScore:
    def test_normal(self):
        assert _derive_structure_score({"smc_score": 85}) == 0.85

    def test_clamps_high(self):
        assert _derive_structure_score({"smc_score": 150}) == 1.0

    def test_clamps_low(self):
        assert _derive_structure_score({"smc_score": -10}) == 0.0

    def test_missing(self):
        assert _derive_structure_score({}) == 0.0

    def test_zero(self):
        assert _derive_structure_score({"smc_score": 0}) == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# §10  Compression Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestCompression:
    def test_blockers_always_fail(self):
        status = _compress_status(
            [L9BlockerCode.UPSTREAM_NOT_CONTINUABLE],
            L9CoherenceBand.HIGH,
            L9FreshnessState.FRESH,
            L9WarmupState.READY,
            L9FallbackClass.NO_FALLBACK,
            [], 0.95, 5,
        )
        assert status == L9Status.FAIL

    def test_low_band_fail(self):
        status = _compress_status(
            [], L9CoherenceBand.LOW,
            L9FreshnessState.FRESH,
            L9WarmupState.READY,
            L9FallbackClass.NO_FALLBACK,
            [], 0.30, 5,
        )
        assert status == L9Status.FAIL

    def test_clean_pass(self):
        status = _compress_status(
            [], L9CoherenceBand.HIGH,
            L9FreshnessState.FRESH,
            L9WarmupState.READY,
            L9FallbackClass.NO_FALLBACK,
            [], 0.90, 3,
        )
        assert status == L9Status.PASS

    def test_no_smc_signal_warn(self):
        status = _compress_status(
            [], L9CoherenceBand.HIGH,
            L9FreshnessState.FRESH,
            L9WarmupState.READY,
            L9FallbackClass.NO_FALLBACK,
            ["NO_SMC_SIGNAL"], 0.85, 3,
        )
        assert status == L9Status.WARN

    def test_degraded_warn(self):
        status = _compress_status(
            [], L9CoherenceBand.MID,
            L9FreshnessState.DEGRADED,
            L9WarmupState.PARTIAL,
            L9FallbackClass.LEGAL_EMERGENCY_PRESERVE,
            [], 0.70, 2,
        )
        assert status == L9Status.WARN


# ═══════════════════════════════════════════════════════════════════════════
# §11  Warning Codes Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestWarningCodes:
    def test_clean(self):
        codes = _collect_warning_codes(
            L9FreshnessState.FRESH, L9WarmupState.READY,
            L9FallbackClass.NO_FALLBACK, L9CoherenceBand.HIGH,
            [], 5,
        )
        assert codes == []

    def test_degraded(self):
        codes = _collect_warning_codes(
            L9FreshnessState.DEGRADED, L9WarmupState.PARTIAL,
            L9FallbackClass.LEGAL_EMERGENCY_PRESERVE, L9CoherenceBand.MID,
            ["NO_DIVERGENCE_DATA"], 2,
        )
        assert "DEGRADED_CONTEXT" in codes
        assert "PARTIAL_WARMUP" in codes
        assert "LEGAL_EMERGENCY_PRESERVE_USED" in codes
        assert "STRUCTURE_MID_BAND" in codes
        assert "LOW_SMC_FEATURE_COUNT" in codes
        assert "NO_DIVERGENCE_DATA" in codes


# ═══════════════════════════════════════════════════════════════════════════
# §12  Full Governor Integration Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestL9GovernorPassEnvelope:
    """PASS envelope: high structure score, fresh, ready, SMC confirmed."""

    def test_status_pass(self):
        gov = L9ConstitutionalGovernor()
        result = gov.evaluate(_l9_analysis(), _upstream_pass())
        assert result["status"] == "PASS"
        assert result["continuation_allowed"] is True
        assert result["coherence_band"] == "HIGH"
        assert result["routing"]["next_legal_targets"] == ["PHASE_4"]

    def test_envelope_structure(self):
        gov = L9ConstitutionalGovernor()
        result = gov.evaluate(_l9_analysis(), _upstream_pass())
        assert result["layer"] == "L9"
        assert result["layer_version"] == "1.0.0"
        assert "timestamp" in result
        assert "features" in result
        assert "routing" in result
        assert "audit" in result

    def test_no_blockers(self):
        gov = L9ConstitutionalGovernor()
        result = gov.evaluate(_l9_analysis(), _upstream_pass())
        assert result["blocker_codes"] == []

    def test_features_populated(self):
        gov = L9ConstitutionalGovernor()
        result = gov.evaluate(_l9_analysis(), _upstream_pass())
        f = result["features"]
        assert f["structure_score"] == 0.85
        assert f["smc_signal"] is True
        assert f["bos_detected"] is True
        # bos + ob + fvg + sweep = 4 features (choch=False)
        assert f["smc_feature_count"] == 4


class TestL9GovernorWarnEnvelope:
    """WARN envelope: mid score or degraded state."""

    def test_mid_score_warn(self):
        gov = L9ConstitutionalGovernor()
        data = _l9_analysis(smc_score=70, confidence=0.70)
        result = gov.evaluate(data, _upstream_pass())
        assert result["status"] == "WARN"
        assert result["continuation_allowed"] is True

    def test_no_smc_signal_warn(self):
        gov = L9ConstitutionalGovernor()
        data = _l9_analysis(smc=False, bos_detected=False, smc_score=85)
        result = gov.evaluate(data, _upstream_pass())
        # Still HIGH band but NO_SMC_SIGNAL → WARN
        assert result["status"] == "WARN"


class TestL9GovernorFailEnvelope:
    """FAIL envelope: blockers or low score."""

    def test_upstream_fail(self):
        gov = L9ConstitutionalGovernor()
        result = gov.evaluate(_l9_analysis(), _upstream_fail())
        assert result["status"] == "FAIL"
        assert result["continuation_allowed"] is False
        assert "UPSTREAM_NOT_CONTINUABLE" in result["blocker_codes"]

    def test_low_score_fail(self):
        gov = L9ConstitutionalGovernor()
        data = _l9_analysis(smc_score=30)
        result = gov.evaluate(data, _upstream_pass())
        assert result["status"] == "FAIL"
        assert result["continuation_allowed"] is False

    def test_no_structure_data_fail(self):
        gov = L9ConstitutionalGovernor()
        data = _l9_fail("no_structure_data")
        result = gov.evaluate(data, _upstream_pass())
        assert result["status"] == "FAIL"
        assert any(
            b in result["blocker_codes"]
            for b in ["REQUIRED_STRUCTURE_SOURCE_MISSING", "FRESHNESS_GOVERNANCE_HARD_FAIL", "WARMUP_INSUFFICIENT"]
        )

    def test_invalid_score_range_fail(self):
        gov = L9ConstitutionalGovernor()
        data = _l9_analysis(smc_score=150)
        result = gov.evaluate(data, _upstream_pass())
        assert result["status"] == "FAIL"
        assert "INVALID_STRUCTURE_STATE" in result["blocker_codes"]

    def test_contract_malformed(self):
        gov = L9ConstitutionalGovernor()
        result = gov.evaluate({}, _upstream_pass())
        assert result["status"] == "FAIL"
        assert "CONTRACT_PAYLOAD_MALFORMED" in result["blocker_codes"]


class TestL9GovernorDefaultUpstream:
    """No upstream provided → defaults to allow."""

    def test_no_upstream(self):
        gov = L9ConstitutionalGovernor()
        result = gov.evaluate(_l9_analysis())
        assert result["status"] == "PASS"
        assert result["continuation_allowed"] is True
