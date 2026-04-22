"""Tests for L7 Constitutional Governor — Strict Mode v1.0.0."""

from __future__ import annotations

from analysis.layers.L7_constitutional import (
    BlockerCode,
    CoherenceBand,
    FallbackClass,
    FreshnessState,
    L7ConstitutionalGovernor,
    L7Status,
    WarmupState,
    _check_contract,
    _check_edge_validation,
    _check_probability_sources,
    _check_upstream,
    _compress_status,
    _derive_win_probability,
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


def _l7_analysis(
    *,
    win_probability: float = 72.0,
    profit_factor: float = 2.1,
    simulations: int = 1000,
    validation: str = "PASS",
    valid: bool = True,
    mc_passed_threshold: bool = True,
    risk_of_ruin: float = 0.02,
    conf12_raw: float = 0.92,
    bayesian_posterior: float = 0.68,
    returns_source: str = "trade_history",
    wf_passed: bool | None = True,
) -> dict:
    return {
        "win_probability": win_probability,
        "profit_factor": profit_factor,
        "simulations": simulations,
        "validation": validation,
        "valid": valid,
        "mc_passed_threshold": mc_passed_threshold,
        "risk_of_ruin": risk_of_ruin,
        "conf12_raw": conf12_raw,
        "bayesian_posterior": bayesian_posterior,
        "returns_source": returns_source,
        "wf_passed": wf_passed,
        "symbol": "EURUSD",
    }


def _l7_fallback() -> dict:
    return {
        "win_probability": 0.0,
        "profit_factor": 0.0,
        "simulations": 0,
        "validation": "FAIL",
        "valid": True,
        "mc_passed_threshold": False,
        "risk_of_ruin": 1.0,
        "conf12_raw": 0.0,
        "bayesian_posterior": 0.0,
        "returns_source": "trade_history",
        "symbol": "EURUSD",
        "note": "insufficient_data_5/30",
    }


# ═══════════════════════════════════════════════════════════════════════════
# §1  Sub-gate unit tests
# ═══════════════════════════════════════════════════════════════════════════


class TestScoreBand:
    def test_high(self):
        assert _score_band(0.72) == CoherenceBand.HIGH

    def test_mid(self):
        assert _score_band(0.60) == CoherenceBand.MID

    def test_low(self):
        assert _score_band(0.50) == CoherenceBand.LOW

    def test_boundary_high(self):
        assert _score_band(0.67) == CoherenceBand.HIGH

    def test_boundary_mid(self):
        assert _score_band(0.55) == CoherenceBand.MID

    def test_boundary_low(self):
        assert _score_band(0.5499) == CoherenceBand.LOW


class TestCheckUpstream:
    def test_pass_when_continuable(self):
        assert _check_upstream({"continuation_allowed": True}) == []

    def test_fail_when_not_continuable(self):
        blockers = _check_upstream({"continuation_allowed": False})
        assert BlockerCode.UPSTREAM_NOT_CONTINUABLE in blockers

    def test_legacy_valid_key(self):
        assert _check_upstream({"valid": True}) == []

    def test_legacy_valid_false(self):
        blockers = _check_upstream({"valid": False})
        assert BlockerCode.UPSTREAM_NOT_CONTINUABLE in blockers

    def test_empty_upstream(self):
        blockers = _check_upstream({})
        assert BlockerCode.UPSTREAM_NOT_CONTINUABLE in blockers


class TestCheckContract:
    def test_valid_contract(self):
        assert _check_contract({"validation": "PASS", "valid": True}) == []

    def test_empty_payload(self):
        blockers = _check_contract({})
        assert BlockerCode.CONTRACT_PAYLOAD_MALFORMED in blockers

    def test_none_payload(self):
        blockers = _check_contract(None)  # type: ignore[arg-type]
        assert BlockerCode.CONTRACT_PAYLOAD_MALFORMED in blockers

    def test_missing_both_keys(self):
        blockers = _check_contract({"symbol": "EURUSD"})
        assert BlockerCode.CONTRACT_PAYLOAD_MALFORMED in blockers


class TestCheckProbabilitySources:
    def test_mc_ran(self):
        assert _check_probability_sources(_l7_analysis()) == []

    def test_mc_not_ran_fallback(self):
        blockers = _check_probability_sources(_l7_fallback())
        assert BlockerCode.REQUIRED_PROBABILITY_SOURCE_MISSING in blockers

    def test_mc_not_ran_but_valid(self):
        """simulations=0 but validation != FAIL → not missing source."""
        data = _l7_analysis(simulations=0, validation="CONDITIONAL")
        assert _check_probability_sources(data) == []


class TestEvalFreshness:
    def test_fresh_real_data(self):
        assert _eval_freshness(_l7_analysis()) == FreshnessState.FRESH

    def test_degraded_synthetic(self):
        assert _eval_freshness(_l7_analysis(returns_source="synthetic")) == FreshnessState.DEGRADED

    def test_stale_preserved(self):
        assert _eval_freshness(_l7_analysis(returns_source="stale_preserved")) == FreshnessState.STALE_PRESERVED

    def test_explicit_state(self):
        data = _l7_analysis()
        data["freshness_state"] = "NO_PRODUCER"
        assert _eval_freshness(data) == FreshnessState.NO_PRODUCER

    def test_no_simulations(self):
        data = _l7_analysis(simulations=0, returns_source="unknown")
        assert _eval_freshness(data) == FreshnessState.DEGRADED


class TestEvalWarmup:
    def test_ready(self):
        assert _eval_warmup(_l7_analysis(simulations=1000)) == WarmupState.READY

    def test_partial(self):
        assert _eval_warmup(_l7_analysis(simulations=200)) == WarmupState.PARTIAL

    def test_insufficient(self):
        assert _eval_warmup(_l7_analysis(simulations=0)) == WarmupState.INSUFFICIENT

    def test_explicit_warmup(self):
        data = _l7_analysis()
        data["warmup_state"] = "PARTIAL"
        assert _eval_warmup(data) == WarmupState.PARTIAL


class TestEvalFallback:
    def test_no_fallback(self):
        assert _eval_fallback(_l7_analysis()) == FallbackClass.NO_FALLBACK

    def test_cluster_primary_substitute(self):
        assert _eval_fallback(_l7_analysis(returns_source="cluster:majors")) == FallbackClass.LEGAL_PRIMARY_SUBSTITUTE

    def test_synthetic_emergency(self):
        assert _eval_fallback(_l7_analysis(returns_source="synthetic")) == FallbackClass.LEGAL_EMERGENCY_PRESERVE

    def test_explicit_illegal(self):
        data = _l7_analysis()
        data["fallback_class"] = "ILLEGAL_FALLBACK"
        assert _eval_fallback(data) == FallbackClass.ILLEGAL_FALLBACK


class TestCheckEdgeValidation:
    def test_pass_gate(self):
        blockers, warnings = _check_edge_validation(_l7_analysis())
        assert blockers == []

    def test_fail_with_mc_ran(self):
        data = _l7_analysis(validation="FAIL", mc_passed_threshold=False, simulations=1000)
        blockers, _ = _check_edge_validation(data)
        assert BlockerCode.EDGE_STATUS_INVALID in blockers

    def test_wf_failed_warning(self):
        data = _l7_analysis(wf_passed=False)
        _, warnings = _check_edge_validation(data)
        assert "WF_VALIDATION_FAILED" in warnings

    def test_wf_skipped_warning(self):
        data = _l7_analysis(wf_passed=None)
        data["wf_skipped_reason"] = "synthetic_returns"
        _, warnings = _check_edge_validation(data)
        assert any("WF_SKIPPED" in w for w in warnings)


class TestDeriveWinProbability:
    def test_percentage_scale(self):
        assert abs(_derive_win_probability({"win_probability": 72.0}) - 0.72) < 1e-6

    def test_fractional_scale(self):
        assert abs(_derive_win_probability({"win_probability": 0.72}) - 0.72) < 1e-6

    def test_zero(self):
        assert _derive_win_probability({"win_probability": 0.0}) == 0.0

    def test_missing(self):
        assert _derive_win_probability({}) == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# §2  Compression logic
# ═══════════════════════════════════════════════════════════════════════════


class TestCompressStatus:
    def test_blockers_always_fail(self):
        status = _compress_status(
            blockers=[BlockerCode.UPSTREAM_NOT_CONTINUABLE],
            band=CoherenceBand.HIGH,
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            edge_warnings=[],
            win_prob=0.80,
            sample_count=1000,
        )
        assert status == L7Status.FAIL

    def test_low_band_fails(self):
        status = _compress_status(
            blockers=[],
            band=CoherenceBand.LOW,
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            edge_warnings=[],
            win_prob=0.40,
            sample_count=1000,
        )
        assert status == L7Status.FAIL

    def test_clean_pass(self):
        status = _compress_status(
            blockers=[],
            band=CoherenceBand.HIGH,
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            edge_warnings=[],
            win_prob=0.72,
            sample_count=1000,
        )
        assert status == L7Status.PASS

    def test_mid_band_warns(self):
        status = _compress_status(
            blockers=[],
            band=CoherenceBand.MID,
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            edge_warnings=[],
            win_prob=0.60,
            sample_count=1000,
        )
        assert status == L7Status.WARN

    def test_degraded_freshness_warns(self):
        status = _compress_status(
            blockers=[],
            band=CoherenceBand.HIGH,
            freshness=FreshnessState.DEGRADED,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            edge_warnings=[],
            win_prob=0.72,
            sample_count=1000,
        )
        assert status == L7Status.WARN

    def test_partial_warmup_warns(self):
        status = _compress_status(
            blockers=[],
            band=CoherenceBand.HIGH,
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.PARTIAL,
            fallback=FallbackClass.NO_FALLBACK,
            edge_warnings=[],
            win_prob=0.72,
            sample_count=1000,
        )
        assert status == L7Status.WARN

    def test_emergency_fallback_warns(self):
        status = _compress_status(
            blockers=[],
            band=CoherenceBand.HIGH,
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.READY,
            fallback=FallbackClass.LEGAL_EMERGENCY_PRESERVE,
            edge_warnings=[],
            win_prob=0.72,
            sample_count=1000,
        )
        assert status == L7Status.WARN

    def test_low_sample_warns(self):
        status = _compress_status(
            blockers=[],
            band=CoherenceBand.HIGH,
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            edge_warnings=[],
            win_prob=0.72,
            sample_count=10,  # below MIN_SAMPLE_WARN
        )
        assert status == L7Status.WARN

    def test_wf_failed_warning_prevents_pass(self):
        status = _compress_status(
            blockers=[],
            band=CoherenceBand.HIGH,
            freshness=FreshnessState.FRESH,
            warmup=WarmupState.READY,
            fallback=FallbackClass.NO_FALLBACK,
            edge_warnings=["WF_VALIDATION_FAILED"],
            win_prob=0.72,
            sample_count=1000,
        )
        # WF_VALIDATION_FAILED contains "FAILED" → clean check fails → WARN
        assert status == L7Status.WARN


# ═══════════════════════════════════════════════════════════════════════════
# §3  Governor integration tests
# ═══════════════════════════════════════════════════════════════════════════


class TestL7GovernorEnvelope:
    def setup_method(self):
        self.gov = L7ConstitutionalGovernor()

    def test_pass_envelope(self):
        env = self.gov.evaluate(_l7_analysis(), _upstream_pass())
        assert env["status"] == "PASS"
        assert env["continuation_allowed"] is True
        assert env["layer"] == "L7"
        assert "L8" in env.get("routing", {}).get("next_legal_targets", [])

    def test_fail_upstream_blocked(self):
        env = self.gov.evaluate(_l7_analysis(), _upstream_fail())
        assert env["status"] == "FAIL"
        assert env["continuation_allowed"] is True  # always-forward
        assert "UPSTREAM_NOT_CONTINUABLE" in env["blocker_codes"]

    def test_fail_fallback_insufficient(self):
        env = self.gov.evaluate(_l7_fallback(), _upstream_pass())
        assert env["status"] == "FAIL"
        assert env["continuation_allowed"] is True  # always-forward

    def test_warn_mid_band(self):
        data = _l7_analysis(win_probability=58.0)  # 0.58 → MID band
        env = self.gov.evaluate(data, _upstream_pass())
        assert env["status"] == "WARN"
        assert env["continuation_allowed"] is True
        assert env["coherence_band"] == "MID"

    def test_fail_low_band(self):
        data = _l7_analysis(
            win_probability=45.0,
            validation="FAIL",
            mc_passed_threshold=False,
        )
        env = self.gov.evaluate(data, _upstream_pass())
        assert env["status"] == "FAIL"
        assert env["continuation_allowed"] is True  # always-forward

    def test_warn_synthetic_returns(self):
        data = _l7_analysis(returns_source="synthetic")
        env = self.gov.evaluate(data, _upstream_pass())
        # Synthetic → DEGRADED freshness + LEGAL_EMERGENCY_PRESERVE → WARN
        assert env["status"] == "WARN"
        assert env["continuation_allowed"] is True
        assert env["freshness_state"] == "DEGRADED"
        assert env["fallback_class"] == "LEGAL_EMERGENCY_PRESERVE"

    def test_features_present(self):
        env = self.gov.evaluate(_l7_analysis(), _upstream_pass())
        feat = env.get("features", {})
        assert "win_probability" in feat
        assert "profit_factor" in feat
        assert "sample_count" in feat
        assert "feature_hash" in feat

    def test_routing_present(self):
        env = self.gov.evaluate(_l7_analysis(), _upstream_pass())
        routing = env.get("routing", {})
        assert "next_legal_targets" in routing
        assert "source_used" in routing

    def test_audit_present(self):
        env = self.gov.evaluate(_l7_analysis(), _upstream_pass())
        audit = env.get("audit", {})
        assert "rule_hits" in audit

    def test_version_present(self):
        env = self.gov.evaluate(_l7_analysis(), _upstream_pass())
        assert env["layer_version"] == "1.0.0"

    def test_no_upstream_defaults_to_pass(self):
        """When upstream_output is None, governor defaults to allowing."""
        env = self.gov.evaluate(_l7_analysis(), None)
        assert env["status"] == "PASS"
        assert env["continuation_allowed"] is True

    def test_fail_contract_malformed(self):
        env = self.gov.evaluate({"symbol": "EURUSD"}, _upstream_pass())
        assert env["status"] == "FAIL"
        assert "CONTRACT_PAYLOAD_MALFORMED" in env["blocker_codes"]

    def test_fail_edge_invalid(self):
        """MC ran but failed thresholds → EDGE_STATUS_INVALID."""
        data = _l7_analysis(
            win_probability=45.0,
            profit_factor=0.8,
            validation="FAIL",
            mc_passed_threshold=False,
            simulations=1000,
        )
        env = self.gov.evaluate(data, _upstream_pass())
        assert env["status"] == "FAIL"
        assert "EDGE_STATUS_INVALID" in env["blocker_codes"] or "WIN_PROBABILITY_BELOW_MINIMUM" in env["blocker_codes"]


# ═══════════════════════════════════════════════════════════════════════════
# §4  L7 Analyzer constitutional wrapper integration
# ═══════════════════════════════════════════════════════════════════════════


class TestL7AnalyzerConstitutionalWrapper:
    """Test that L7ProbabilityAnalyzer wraps output with constitutional envelope."""

    def test_analyze_includes_constitutional(self):
        from analysis.layers.L7_probability import L7ProbabilityAnalyzer

        analyzer = L7ProbabilityAnalyzer(simulations=100, seed=42)
        returns = [0.01, -0.005, 0.02, -0.01, 0.015] * 10  # 50 trades
        result = analyzer.analyze("EURUSD", trade_returns=returns)
        assert "constitutional" in result
        assert "continuation_allowed" in result

    def test_fallback_includes_constitutional(self):
        from analysis.layers.L7_probability import L7ProbabilityAnalyzer

        analyzer = L7ProbabilityAnalyzer(simulations=100, seed=42)
        returns = [0.01, -0.005]  # too few → fallback
        result = analyzer.analyze("EURUSD", trade_returns=returns)
        assert "constitutional" in result
        assert result["validation"] == "FAIL"

    def test_cluster_fallback_degrades_to_warn_not_fail(self):
        from analysis.layers.L7_probability import L7ProbabilityAnalyzer

        analyzer = L7ProbabilityAnalyzer(simulations=100, seed=42)
        result = analyzer.analyze(
            "EURUSD",
            trade_returns=[0.01, -0.005],
            cluster_pool={"majors": [0.02, -0.01, 0.015, -0.004] * 15},
        )

        const = result.get("constitutional", {})
        assert result["validation"] == "CONDITIONAL"
        assert const.get("status") == "WARN"
        assert const.get("fallback_class") == "LEGAL_PRIMARY_SUBSTITUTE"
        assert "PRIMARY_SUBSTITUTE_USED" in const.get("warning_codes", [])

    def test_upstream_injection(self):
        from analysis.layers.L7_probability import L7ProbabilityAnalyzer

        analyzer = L7ProbabilityAnalyzer(simulations=100, seed=42)
        analyzer.set_upstream_output({"valid": False, "continuation_allowed": False})
        returns = [0.01, -0.005, 0.02, -0.01, 0.015] * 10
        result = analyzer.analyze("EURUSD", trade_returns=returns)
        const = result.get("constitutional", {})
        assert const.get("status") == "FAIL"
        assert "UPSTREAM_NOT_CONTINUABLE" in const.get("blocker_codes", [])
