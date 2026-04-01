"""Tests for L8 Constitutional Governor — Strict Mode v1.0.0."""

from __future__ import annotations

from analysis.layers.L8_constitutional import (
    L8BlockerCode,
    L8CoherenceBand,
    L8ConstitutionalGovernor,
    L8FallbackClass,
    L8FreshnessState,
    L8Status,
    L8WarmupState,
    _check_contract,
    _check_integrity_sources,
    _check_tii_validation,
    _check_upstream,
    _collect_warning_codes,
    _compress_status,
    _derive_integrity_score,
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


def _l8_analysis(
    *,
    tii_sym: float = 0.92,
    tii_status: str = "STRONG",
    tii_grade: str = "STRONG",
    integrity: float = 0.90,
    twms_score: float = 0.85,
    gate_status: str = "OPEN",
    gate_passed: bool = True,
    valid: bool = True,
    components: dict | None = None,
    twms_signals: dict | None = None,
    computed_vwap: float = 1.12345,
    computed_energy: float = 5.5,
    computed_bias: float = 0.002,
    note: str = "",
    core_enhanced: bool = False,
) -> dict:
    if components is None:
        components = {
            "trend": 0.8, "momentum": 0.7, "volatility": 0.6, "volume": 0.5,
            "correlation": 0.4, "rsi": 0.6, "macd": 0.7, "cci": 0.5,
            "mfi": 0.6, "atr": 0.8,
        }
    if twms_signals is None:
        twms_signals = {"rsi": "BUY", "macd": "BUY", "cci": "NEUTRAL"}
    return {
        "tii_sym": tii_sym,
        "tii_status": tii_status,
        "tii_grade": tii_grade,
        "integrity": integrity,
        "twms_score": twms_score,
        "gate_status": gate_status,
        "gate_passed": gate_passed,
        "valid": valid,
        "components": components,
        "twms_signals": twms_signals,
        "computed_vwap": computed_vwap,
        "computed_energy": computed_energy,
        "computed_bias": computed_bias,
        "note": note,
        "core_enhanced": core_enhanced,
        "symbol": "EURUSD",
    }


def _l8_minimal() -> dict:
    return {
        "tii_sym": 0.50,
        "tii_status": "ACCEPTABLE",
        "tii_grade": "ACCEPTABLE",
        "integrity": 0.50,
        "twms_score": 0.50,
        "gate_status": "CLOSED",
        "gate_passed": False,
        "valid": True,
        "components": {},
        "twms_signals": {},
        "computed_vwap": 0.0,
        "computed_energy": 0.0,
        "computed_bias": 0.0,
        "note": "minimal_fallback",
        "symbol": "EURUSD",
    }


# ═══════════════════════════════════════════════════════════════════════════
# §1  Score Band Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestScoreBand:
    def test_high_band(self):
        assert _score_band(0.88) == L8CoherenceBand.HIGH
        assert _score_band(0.95) == L8CoherenceBand.HIGH

    def test_mid_band(self):
        assert _score_band(0.75) == L8CoherenceBand.MID
        assert _score_band(0.87) == L8CoherenceBand.MID

    def test_low_band(self):
        assert _score_band(0.74) == L8CoherenceBand.LOW
        assert _score_band(0.50) == L8CoherenceBand.LOW
        assert _score_band(0.0) == L8CoherenceBand.LOW


# ═══════════════════════════════════════════════════════════════════════════
# §2  Upstream Check Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestUpstreamCheck:
    def test_pass(self):
        assert _check_upstream(_upstream_pass()) == []

    def test_fail(self):
        blockers = _check_upstream(_upstream_fail())
        assert L8BlockerCode.UPSTREAM_NOT_CONTINUABLE in blockers

    def test_empty(self):
        blockers = _check_upstream({})
        assert L8BlockerCode.UPSTREAM_NOT_CONTINUABLE in blockers


# ═══════════════════════════════════════════════════════════════════════════
# §3  Contract Check Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestContractCheck:
    def test_valid(self):
        assert _check_contract(_l8_analysis()) == []

    def test_empty(self):
        blockers = _check_contract({})
        assert L8BlockerCode.CONTRACT_PAYLOAD_MALFORMED in blockers

    def test_none(self):
        blockers = _check_contract({})
        assert L8BlockerCode.CONTRACT_PAYLOAD_MALFORMED in blockers


# ═══════════════════════════════════════════════════════════════════════════
# §4  Integrity Source Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestIntegritySources:
    def test_all_available(self):
        assert _check_integrity_sources(_l8_analysis()) == []

    def test_tii_missing(self):
        data = {"valid": False}
        blockers = _check_integrity_sources(data)
        assert L8BlockerCode.TII_UNAVAILABLE in blockers

    def test_twms_missing(self):
        data = {"tii_sym": 0.8, "valid": False}
        blockers = _check_integrity_sources(data)
        assert L8BlockerCode.TWMS_UNAVAILABLE in blockers


# ═══════════════════════════════════════════════════════════════════════════
# §5  Freshness Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestFreshness:
    def test_explicit(self):
        data = {**_l8_analysis(), "freshness_state": "STALE_PRESERVED"}
        assert _eval_freshness(data) == L8FreshnessState.STALE_PRESERVED

    def test_minimal_fallback(self):
        assert _eval_freshness(_l8_minimal()) == L8FreshnessState.DEGRADED

    def test_valid_tii(self):
        assert _eval_freshness(_l8_analysis()) == L8FreshnessState.FRESH

    def test_invalid(self):
        data = {"valid": False, "tii_sym": 0.0}
        assert _eval_freshness(data) == L8FreshnessState.DEGRADED


# ═══════════════════════════════════════════════════════════════════════════
# §6  Warmup Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestWarmup:
    def test_ready(self):
        assert _eval_warmup(_l8_analysis()) == L8WarmupState.READY

    def test_partial(self):
        data = {**_l8_analysis(), "components": {"trend": 0.8, "momentum": 0.7}}
        assert _eval_warmup(data) == L8WarmupState.PARTIAL

    def test_insufficient(self):
        data = {"valid": False}
        assert _eval_warmup(data) == L8WarmupState.INSUFFICIENT

    def test_explicit(self):
        data = {**_l8_analysis(), "warmup_state": "PARTIAL"}
        assert _eval_warmup(data) == L8WarmupState.PARTIAL


# ═══════════════════════════════════════════════════════════════════════════
# §7  Fallback Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestFallback:
    def test_no_fallback(self):
        data = _l8_analysis()
        assert _eval_fallback(data) == L8FallbackClass.LEGAL_PRIMARY_SUBSTITUTE

    def test_core_enhanced(self):
        data = {**_l8_analysis(), "core_enhanced": True}
        assert _eval_fallback(data) == L8FallbackClass.NO_FALLBACK

    def test_minimal_fallback(self):
        assert _eval_fallback(_l8_minimal()) == L8FallbackClass.LEGAL_EMERGENCY_PRESERVE

    def test_explicit(self):
        data = {**_l8_analysis(), "fallback_class": "ILLEGAL_FALLBACK"}
        assert _eval_fallback(data) == L8FallbackClass.ILLEGAL_FALLBACK


# ═══════════════════════════════════════════════════════════════════════════
# §8  TII Validation Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTIIValidation:
    def test_gate_open(self):
        blockers, warnings = _check_tii_validation(_l8_analysis())
        assert not blockers
        assert "TII_GATE_CLOSED" not in warnings

    def test_gate_closed(self):
        data = {**_l8_analysis(), "gate_status": "CLOSED", "gate_passed": False}
        blockers, warnings = _check_tii_validation(data)
        assert not blockers
        assert "TII_GATE_CLOSED" in warnings

    def test_weak_tii(self):
        data = {**_l8_analysis(), "tii_status": "WEAK"}
        _, warnings = _check_tii_validation(data)
        assert "TII_STATUS_WEAK" in warnings

    def test_invalid_tii_range(self):
        data = {**_l8_analysis(), "tii_sym": 1.5}
        blockers, _ = _check_tii_validation(data)
        assert L8BlockerCode.INVALID_INTEGRITY_STATE in blockers


# ═══════════════════════════════════════════════════════════════════════════
# §9  Integrity Score Derivation
# ═══════════════════════════════════════════════════════════════════════════


class TestIntegrityScore:
    def test_normal(self):
        assert _derive_integrity_score({"integrity": 0.85}) == 0.85

    def test_clamps_high(self):
        assert _derive_integrity_score({"integrity": 1.5}) == 1.0

    def test_clamps_low(self):
        assert _derive_integrity_score({"integrity": -0.2}) == 0.0

    def test_missing(self):
        assert _derive_integrity_score({}) == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# §10  Compression Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestCompression:
    def test_blockers_always_fail(self):
        status = _compress_status(
            [L8BlockerCode.UPSTREAM_NOT_CONTINUABLE],
            L8CoherenceBand.HIGH,
            L8FreshnessState.FRESH,
            L8WarmupState.READY,
            L8FallbackClass.NO_FALLBACK,
            [], 0.95, 10,
        )
        assert status == L8Status.FAIL

    def test_low_band_fail(self):
        status = _compress_status(
            [], L8CoherenceBand.LOW,
            L8FreshnessState.FRESH,
            L8WarmupState.READY,
            L8FallbackClass.NO_FALLBACK,
            [], 0.50, 10,
        )
        assert status == L8Status.FAIL

    def test_clean_pass(self):
        status = _compress_status(
            [], L8CoherenceBand.HIGH,
            L8FreshnessState.FRESH,
            L8WarmupState.READY,
            L8FallbackClass.NO_FALLBACK,
            [], 0.95, 10,
        )
        assert status == L8Status.PASS

    def test_degraded_warn(self):
        status = _compress_status(
            [], L8CoherenceBand.MID,
            L8FreshnessState.DEGRADED,
            L8WarmupState.PARTIAL,
            L8FallbackClass.LEGAL_EMERGENCY_PRESERVE,
            [], 0.80, 5,
        )
        assert status == L8Status.WARN

    def test_gate_closed_warns(self):
        status = _compress_status(
            [], L8CoherenceBand.HIGH,
            L8FreshnessState.FRESH,
            L8WarmupState.READY,
            L8FallbackClass.NO_FALLBACK,
            ["TII_GATE_CLOSED"], 0.90, 10,
        )
        assert status == L8Status.WARN


# ═══════════════════════════════════════════════════════════════════════════
# §11  Warning Codes Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestWarningCodes:
    def test_clean(self):
        codes = _collect_warning_codes(
            L8FreshnessState.FRESH, L8WarmupState.READY,
            L8FallbackClass.NO_FALLBACK, L8CoherenceBand.HIGH,
            [], 10, "OPEN",
        )
        assert codes == []

    def test_degraded(self):
        codes = _collect_warning_codes(
            L8FreshnessState.DEGRADED, L8WarmupState.PARTIAL,
            L8FallbackClass.LEGAL_EMERGENCY_PRESERVE, L8CoherenceBand.MID,
            [], 5, "CLOSED",
        )
        assert "DEGRADED_CONTEXT" in codes
        assert "PARTIAL_WARMUP" in codes
        assert "LEGAL_EMERGENCY_PRESERVE_USED" in codes
        assert "INTEGRITY_MID_BAND" in codes
        assert "TII_GATE_CLOSED" in codes


# ═══════════════════════════════════════════════════════════════════════════
# §12  Full Governor Integration Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestL8GovernorPassEnvelope:
    """PASS envelope: high integrity, fresh, ready, gate open."""

    def test_status_pass(self):
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(_l8_analysis(), _upstream_pass())
        assert result["status"] == "PASS"
        assert result["continuation_allowed"] is True
        assert result["coherence_band"] == "HIGH"
        assert result["routing"]["next_legal_targets"] == ["L9"]

    def test_envelope_structure(self):
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(_l8_analysis(), _upstream_pass())
        assert result["layer"] == "L8"
        assert result["layer_version"] == "1.0.0"
        assert "timestamp" in result
        assert "features" in result
        assert "routing" in result
        assert "audit" in result

    def test_no_blockers(self):
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(_l8_analysis(), _upstream_pass())
        assert result["blocker_codes"] == []


class TestL8GovernorWarnEnvelope:
    """WARN envelope: mid integrity or degraded state."""

    def test_mid_integrity_warn(self):
        gov = L8ConstitutionalGovernor()
        data = _l8_analysis(integrity=0.80, tii_sym=0.80)
        result = gov.evaluate(data, _upstream_pass())
        assert result["status"] == "WARN"
        assert result["continuation_allowed"] is True

    def test_degraded_freshness_warn(self):
        gov = L8ConstitutionalGovernor()
        data = {**_l8_analysis(), "freshness_state": "DEGRADED"}
        result = gov.evaluate(data, _upstream_pass())
        assert result["status"] == "WARN"


class TestL8GovernorFailEnvelope:
    """FAIL envelope: blockers or low score."""

    def test_upstream_fail(self):
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(_l8_analysis(), _upstream_fail())
        assert result["status"] == "FAIL"
        assert result["continuation_allowed"] is False
        assert "UPSTREAM_NOT_CONTINUABLE" in result["blocker_codes"]

    def test_low_integrity_fail(self):
        gov = L8ConstitutionalGovernor()
        data = _l8_analysis(integrity=0.50, tii_sym=0.50)
        result = gov.evaluate(data, _upstream_pass())
        assert result["status"] == "FAIL"
        assert result["continuation_allowed"] is False

    def test_missing_source_fail(self):
        gov = L8ConstitutionalGovernor()
        data = {"valid": False}
        result = gov.evaluate(data, _upstream_pass())
        assert result["status"] == "FAIL"
        assert any(
            b in result["blocker_codes"]
            for b in ["TII_UNAVAILABLE", "TWMS_UNAVAILABLE", "WARMUP_INSUFFICIENT"]
        )

    def test_invalid_state_fail(self):
        gov = L8ConstitutionalGovernor()
        data = _l8_analysis(tii_sym=1.5)
        result = gov.evaluate(data, _upstream_pass())
        assert result["status"] == "FAIL"
        assert "INVALID_INTEGRITY_STATE" in result["blocker_codes"]

    def test_contract_malformed(self):
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate({}, _upstream_pass())
        assert result["status"] == "FAIL"
        assert "CONTRACT_PAYLOAD_MALFORMED" in result["blocker_codes"]


class TestL8GovernorMinimalFallback:
    """Minimal fallback produces WARN (emergency preserve)."""

    def test_minimal_fallback(self):
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(_l8_minimal(), _upstream_pass())
        # Minimal has integrity=0.50 → LOW band → FAIL
        assert result["status"] == "FAIL"
        assert result["fallback_class"] == "LEGAL_EMERGENCY_PRESERVE"


class TestL8GovernorDefaultUpstream:
    """No upstream provided → defaults to allow."""

    def test_no_upstream(self):
        gov = L8ConstitutionalGovernor()
        result = gov.evaluate(_l8_analysis())
        assert result["status"] == "PASS"
        assert result["continuation_allowed"] is True
