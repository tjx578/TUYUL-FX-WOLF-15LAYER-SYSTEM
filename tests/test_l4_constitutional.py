"""Tests for L4 Constitutional Governor — Strict Mode v1.0.0."""

from __future__ import annotations

from analysis.layers.L4_constitutional import (
    BlockerCode,
    CoherenceBand,
    FallbackClass,
    FreshnessState,
    L4ConstitutionalGovernor,
    L4Status,
    WarmupState,
    _check_contract_payload,
    _check_fallback,
    _check_freshness,
    _check_required_sources,
    _check_session_validity,
    _check_upstream_legality,
    _check_warmup,
    _compress_status,
    _score_band,
)

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _l3_pass() -> dict:
    return {"valid": True, "continuation_allowed": True}


def _l3_fail() -> dict:
    return {"valid": False, "continuation_allowed": False}


def _l4_analysis(
    *,
    session: str = "LONDON",
    quality: float = 0.90,
    tradeable: bool = True,
    wolf_total: float = 28.0,
    grade: str = "EXCELLENT",
    ev: float = 0.15,
    ci: float = 0.90,
    valid: bool = True,
    f_score: float = 10.0,
) -> dict:
    return {
        "session": session,
        "quality": quality,
        "tradeable": tradeable,
        "valid": valid,
        "grade": grade,
        "wolf_30_point": {"total": wolf_total, "f_score": f_score},
        "bayesian": {
            "expected_value": ev,
            "confidence_index": ci,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# §1  Sub-gate unit tests
# ═══════════════════════════════════════════════════════════════════════════


class TestScoreBand:
    def test_high(self):
        assert _score_band(0.90) == CoherenceBand.HIGH

    def test_mid(self):
        assert _score_band(0.75) == CoherenceBand.MID

    def test_low(self):
        assert _score_band(0.50) == CoherenceBand.LOW

    def test_boundary_high(self):
        assert _score_band(0.85) == CoherenceBand.HIGH

    def test_boundary_mid(self):
        assert _score_band(0.65) == CoherenceBand.MID

    def test_boundary_low(self):
        assert _score_band(0.6499) == CoherenceBand.LOW


class TestUpstreamLegality:
    def test_pass_when_continuable(self):
        assert _check_upstream_legality({"continuation_allowed": True}) == []

    def test_fail_when_not_continuable(self):
        blockers = _check_upstream_legality({"continuation_allowed": False})
        assert BlockerCode.UPSTREAM_L3_NOT_CONTINUABLE in blockers

    def test_legacy_valid_key(self):
        assert _check_upstream_legality({"valid": True}) == []

    def test_legacy_valid_false(self):
        blockers = _check_upstream_legality({"valid": False})
        assert BlockerCode.UPSTREAM_L3_NOT_CONTINUABLE in blockers


class TestContractPayload:
    def test_valid(self):
        assert _check_contract_payload("ref", "ts") == []

    def test_empty_ref(self):
        assert BlockerCode.CONTRACT_PAYLOAD_MALFORMED in _check_contract_payload("", "ts")

    def test_empty_timestamp(self):
        assert BlockerCode.CONTRACT_PAYLOAD_MALFORMED in _check_contract_payload("ref", "")


class TestRequiredSources:
    def test_all_present(self):
        blockers, notes = _check_required_sources(["a", "b"], ["a", "b", "c"])
        assert blockers == []

    def test_missing(self):
        blockers, notes = _check_required_sources(["a", "b"], ["a"])
        assert BlockerCode.REQUIRED_SESSION_SOURCE_MISSING in blockers
        assert "b" in notes[0]


class TestFreshness:
    def test_fresh(self):
        blockers, warnings = _check_freshness(FreshnessState.FRESH)
        assert blockers == []
        assert warnings == []

    def test_no_producer(self):
        blockers, _ = _check_freshness(FreshnessState.NO_PRODUCER)
        assert BlockerCode.FRESHNESS_GOVERNANCE_HARD_FAIL in blockers

    def test_stale_preserved(self):
        _, warnings = _check_freshness(FreshnessState.STALE_PRESERVED)
        assert "STALE_PRESERVED_CONTEXT" in warnings

    def test_degraded(self):
        _, warnings = _check_freshness(FreshnessState.DEGRADED)
        assert "DEGRADED_CONTEXT" in warnings


class TestWarmup:
    def test_ready(self):
        blockers, warnings = _check_warmup(WarmupState.READY)
        assert blockers == []

    def test_insufficient(self):
        blockers, _ = _check_warmup(WarmupState.INSUFFICIENT)
        assert BlockerCode.WARMUP_INSUFFICIENT in blockers

    def test_partial(self):
        _, warnings = _check_warmup(WarmupState.PARTIAL)
        assert "PARTIAL_WARMUP" in warnings


class TestFallback:
    def test_no_fallback(self):
        blockers, warnings, rules = _check_fallback(FallbackClass.NO_FALLBACK)
        assert blockers == []
        assert warnings == []

    def test_illegal(self):
        blockers, _, _ = _check_fallback(FallbackClass.ILLEGAL_FALLBACK)
        assert BlockerCode.FALLBACK_DECLARED_BUT_NOT_ALLOWED in blockers

    def test_emergency_preserve(self):
        _, warnings, _ = _check_fallback(FallbackClass.LEGAL_EMERGENCY_PRESERVE)
        assert "LEGAL_EMERGENCY_PRESERVE_USED" in warnings

    def test_primary_substitute(self):
        _, _, rules = _check_fallback(FallbackClass.LEGAL_PRIMARY_SUBSTITUTE)
        assert "LEGAL_PRIMARY_SUBSTITUTE" in rules


class TestSessionValidity:
    def test_valid(self):
        assert _check_session_validity(True, True) == []

    def test_invalid_session(self):
        blockers = _check_session_validity(False, True)
        assert BlockerCode.SESSION_STATE_INVALID in blockers

    def test_no_expectancy(self):
        blockers = _check_session_validity(True, False)
        assert BlockerCode.SESSION_EXPECTANCY_UNAVAILABLE in blockers


# ═══════════════════════════════════════════════════════════════════════════
# §2  Compression logic tests
# ═══════════════════════════════════════════════════════════════════════════


class TestCompressionLogic:
    def test_fail_on_blockers(self):
        status, cont = _compress_status(
            [BlockerCode.UPSTREAM_L3_NOT_CONTINUABLE],
            CoherenceBand.HIGH,
            FreshnessState.FRESH,
            WarmupState.READY,
            FallbackClass.NO_FALLBACK,
            True,
            False,
        )
        assert status == L4Status.FAIL
        assert cont is True  # Always-forward: scoring only, L12 decides

    def test_fail_on_low_band(self):
        status, cont = _compress_status(
            [],
            CoherenceBand.LOW,
            FreshnessState.FRESH,
            WarmupState.READY,
            FallbackClass.NO_FALLBACK,
            True,
            False,
        )
        assert status == L4Status.FAIL
        assert cont is True  # Always-forward: scoring only, L12 decides

    def test_pass_on_clean_envelope(self):
        status, cont = _compress_status(
            [],
            CoherenceBand.HIGH,
            FreshnessState.FRESH,
            WarmupState.READY,
            FallbackClass.NO_FALLBACK,
            True,
            False,
        )
        assert status == L4Status.PASS
        assert cont is True

    def test_warn_on_mid_band(self):
        status, cont = _compress_status(
            [],
            CoherenceBand.MID,
            FreshnessState.FRESH,
            WarmupState.READY,
            FallbackClass.NO_FALLBACK,
            True,
            False,
        )
        assert status == L4Status.WARN
        assert cont is True

    def test_warn_on_non_prime(self):
        status, cont = _compress_status(
            [],
            CoherenceBand.HIGH,
            FreshnessState.FRESH,
            WarmupState.READY,
            FallbackClass.NO_FALLBACK,
            False,
            False,
        )
        assert status == L4Status.WARN
        assert cont is True

    def test_warn_on_degraded_scoring(self):
        status, cont = _compress_status(
            [],
            CoherenceBand.HIGH,
            FreshnessState.FRESH,
            WarmupState.READY,
            FallbackClass.NO_FALLBACK,
            True,
            True,
        )
        assert status == L4Status.WARN
        assert cont is True

    def test_warn_on_stale_freshness(self):
        status, cont = _compress_status(
            [],
            CoherenceBand.HIGH,
            FreshnessState.STALE_PRESERVED,
            WarmupState.READY,
            FallbackClass.NO_FALLBACK,
            True,
            False,
        )
        assert status == L4Status.WARN
        assert cont is True

    def test_pass_with_primary_substitute(self):
        status, cont = _compress_status(
            [],
            CoherenceBand.HIGH,
            FreshnessState.FRESH,
            WarmupState.READY,
            FallbackClass.LEGAL_PRIMARY_SUBSTITUTE,
            True,
            False,
        )
        assert status == L4Status.PASS
        assert cont is True

    def test_warn_on_emergency_preserve(self):
        status, cont = _compress_status(
            [],
            CoherenceBand.HIGH,
            FreshnessState.FRESH,
            WarmupState.READY,
            FallbackClass.LEGAL_EMERGENCY_PRESERVE,
            True,
            False,
        )
        assert status == L4Status.WARN
        assert cont is True


# ═══════════════════════════════════════════════════════════════════════════
# §3  Governor integration tests
# ═══════════════════════════════════════════════════════════════════════════


class TestL4Governor:
    def setup_method(self):
        self.gov = L4ConstitutionalGovernor()

    def test_pass_clean_envelope(self):
        result = self.gov.evaluate(
            l3_output=_l3_pass(),
            l4_analysis=_l4_analysis(),
            symbol="EURUSD",
        )
        assert result["status"] == "PASS"
        assert result["continuation_allowed"] is True
        assert result["routing"]["next_legal_targets"] == ["L5"]
        assert result["layer"] == "L4"
        assert result["layer_version"] == "1.0.0"

    def test_fail_upstream_l3_not_continuable(self):
        result = self.gov.evaluate(
            l3_output=_l3_fail(),
            l4_analysis=_l4_analysis(),
            symbol="EURUSD",
        )
        assert result["status"] == "FAIL"
        assert result["continuation_allowed"] is True  # Always-forward
        assert "UPSTREAM_L3_NOT_CONTINUABLE" in result["blocker_codes"]

    def test_fail_low_wolf_score(self):
        result = self.gov.evaluate(
            l3_output=_l3_pass(),
            l4_analysis=_l4_analysis(wolf_total=5.0, grade="FAIL", ci=0.0),
            symbol="EURUSD",
        )
        assert result["status"] == "FAIL"
        assert result["continuation_allowed"] is True  # Always-forward
        assert result["coherence_band"] == "LOW"

    def test_warn_non_prime_session(self):
        result = self.gov.evaluate(
            l3_output=_l3_pass(),
            l4_analysis=_l4_analysis(quality=0.40),
            symbol="EURUSD",
        )
        assert result["continuation_allowed"] is True
        assert "NON_PRIME_BUT_LEGAL_SESSION" in result["warning_codes"]

    def test_warn_degraded_grade(self):
        result = self.gov.evaluate(
            l3_output=_l3_pass(),
            l4_analysis=_l4_analysis(grade="FAIL"),
            symbol="EURUSD",
        )
        assert result["continuation_allowed"] is True
        assert "DEGRADED_SCORING_MODE" in result["warning_codes"]

    def test_fail_no_session(self):
        analysis = _l4_analysis()
        analysis["session"] = ""
        result = self.gov.evaluate(
            l3_output=_l3_pass(),
            l4_analysis=analysis,
            symbol="EURUSD",
        )
        # session_engine source missing → blocker
        assert result["status"] == "FAIL"
        assert result["continuation_allowed"] is True  # Always-forward
        assert "REQUIRED_SESSION_SOURCE_MISSING" in result["blocker_codes"]

    def test_fail_no_bayesian_expectancy(self):
        analysis = _l4_analysis()
        analysis["bayesian"] = {}
        result = self.gov.evaluate(
            l3_output=_l3_pass(),
            l4_analysis=analysis,
            symbol="EURUSD",
        )
        assert result["status"] == "FAIL"
        assert "SESSION_EXPECTANCY_UNAVAILABLE" in result["blocker_codes"]

    def test_fail_invalid_session(self):
        result = self.gov.evaluate(
            l3_output=_l3_pass(),
            l4_analysis=_l4_analysis(valid=False),
            symbol="EURUSD",
        )
        assert result["status"] == "FAIL"
        assert "SESSION_STATE_INVALID" in result["blocker_codes"]

    def test_fail_no_wolf_data(self):
        analysis = _l4_analysis()
        analysis["wolf_30_point"] = {}
        result = self.gov.evaluate(
            l3_output=_l3_pass(),
            l4_analysis=analysis,
            symbol="EURUSD",
        )
        assert result["status"] == "FAIL"
        assert result["warmup_state"] == "INSUFFICIENT"

    def test_features_contain_score_details(self):
        result = self.gov.evaluate(
            l3_output=_l3_pass(),
            l4_analysis=_l4_analysis(),
            symbol="EURUSD",
        )
        fv = result["features"]["feature_vector"]
        assert "session_score" in fv
        assert "wolf_total" in fv
        assert "grade" in fv

    def test_audit_contains_rule_hits(self):
        result = self.gov.evaluate(
            l3_output=_l3_pass(),
            l4_analysis=_l4_analysis(),
            symbol="EURUSD",
        )
        assert any("score_band=" in rh for rh in result["audit"]["rule_hits"])
        assert any("wolf_total=" in rh for rh in result["audit"]["rule_hits"])

    def test_output_contract_keys(self):
        result = self.gov.evaluate(
            l3_output=_l3_pass(),
            l4_analysis=_l4_analysis(),
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
            "score_numeric",
            "features",
            "routing",
            "audit",
        }
        assert required_keys.issubset(result.keys())

    def test_not_tradeable_produces_degraded_freshness(self):
        result = self.gov.evaluate(
            l3_output=_l3_pass(),
            l4_analysis=_l4_analysis(tradeable=False),
            symbol="EURUSD",
        )
        assert result["freshness_state"] == "DEGRADED"
        assert "DEGRADED_CONTEXT" in result["warning_codes"]
