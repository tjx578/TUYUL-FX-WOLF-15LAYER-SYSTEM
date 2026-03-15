"""
Tests for L5 Psychology & Fundamental Context Layer (merged).
Zone: analysis/ — pure computation, no side-effects.
"""

from datetime import UTC, datetime

import pytest

from analysis.layers.L5_psychology_fundamental import (
    L5AnalysisLayer,
    L5PsychologyAnalyzer,
    PsychGate,  # pyright: ignore[reportAttributeAccessIssue]
    _classify_bias,
    _compute_fundamental_strength,
    _eaf_score,
    _emotional_bias,
    _evaluate_gates,  # pyright: ignore[reportAttributeAccessIssue]
    _extract_pair_currencies,
    _focus_level,
    analyze_fundamental,
    analyze_l5,
)

# ── Fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def layer():
    return L5AnalysisLayer()


@pytest.fixture
def fixed_now():
    return datetime(2026, 2, 16, 12, 0, 0, tzinfo=UTC)


def _good_sentiment():
    return {"sentiment_score": 0.45, "news_count": 5, "impact_level": "LOW"}


def _risk_sentiment():
    return {"sentiment_score": -0.3, "news_count": 4, "impact_level": "HIGH"}


def _make_full_gate_data(score_per_sub: int = 3) -> dict:
    """All 10 gates with uniform sub-score."""
    # Define gate structure locally or retrieve from module;
    # uses the mental model: 10 gates with 3 sub-fields each, max score per sub = 3
    gates = [
        ("PHYSICAL_STATE", [("sleep_quality", 3), ("health_status", 3), ("substances_clear", 3)]),
        ("EMOTIONAL_BASELINE", [("stress_level", 3), ("anxiety_index", 3), ("mood_stability", 3)]),
        ("SESSION_STRUCTURE", [("session_planned", 3), ("breaks_taken", 3), ("routine_consistency", 3)]),
        ("DECISION_CLARITY", [("trade_thesis", 3), ("entry_confidence", 3), ("risk_acceptance", 3)]),
        ("LOSS_RESILIENCE", [("drawdown_tolerance", 3), ("consecutive_loss_ok", 3), ("recovery_mindset", 3)]),
        ("DISCIPLINE_EXECUTION", [("plan_adherence", 3), ("no_revenge", 3), ("size_respect", 3)]),
        ("MICRO_MOMENT_FOCUS", [("alert_level", 3), ("chart_attention", 3), ("trade_readiness", 3)]),
        ("MTA_HIERARCHY", [("sequence_correct", 3), ("compliance", 3), ("no_violations", 3)]),
        ("BODY_CLOSE_PATIENCE", [("h4_discipline", 3), ("patience_level", 3), ("wait_capability", 3)]),
        ("DECISION_GATE_FOCUS", [("proximity_focus", 3), ("precision", 3), ("no_mid_range", 3)]),
    ]
    result = {}
    for gate_name, sub_defs in gates:
        result[gate_name] = {k: min(score_per_sub, mx) for k, mx in sub_defs}
    return result


# ═══════════════════════════════════════════════════════════════════════
# FUNDAMENTAL HELPERS
# ═══════════════════════════════════════════════════════════════════════

class TestExtractPairCurrencies:
    def test_standard_pair(self):
        assert _extract_pair_currencies("GBPUSD") == ("GBP", "USD")

    def test_slash_pair(self):
        assert _extract_pair_currencies("EUR/JPY") == ("EUR", "JPY")

    def test_unknown_returns_none(self):
        assert _extract_pair_currencies("XYZABC") == (None, None)

    def test_short_string(self):
        assert _extract_pair_currencies("GBP") == (None, None)


class TestClassifyBias:
    def test_strong_bullish(self):
        assert _classify_bias(0.50, 5) == "BULLISH"

    def test_strong_bearish(self):
        assert _classify_bias(-0.45, 3) == "BEARISH"

    def test_moderate_lean(self):
        assert _classify_bias(0.25, 2) == "LEAN_BULLISH"

    def test_neutral_no_data(self):
        assert _classify_bias(0.05, 0) == "NEUTRAL"


class TestFundamentalStrength:
    def test_high_impact_strong_sentiment(self):
        s = _compute_fundamental_strength(0.5, 5, "HIGH")
        assert 0.7 <= s <= 1.0

    def test_no_data_zero(self):
        s = _compute_fundamental_strength(0.0, 0, "NONE")
        assert s == 0.0

    def test_bounded_0_1(self):
        s = _compute_fundamental_strength(999.0, 999, "CRITICAL")
        assert 0.0 <= s <= 1.0


# ═══════════════════════════════════════════════════════════════════════
# PSYCHOLOGY HELPERS
# ═══════════════════════════════════════════════════════════════════════

class TestFocusLevel:
    def test_initial_focus(self):
        assert _focus_level(0.0) == 0.90

    def test_peak_focus(self):
        assert abs(_focus_level(3.0) - 0.95) < 0.01

    def test_degraded_focus(self):
        assert _focus_level(8.0) < 0.60


class TestEmotionalBias:
    def test_zero_losses_zero_dd(self):
        assert _emotional_bias(0, 0.0) == 0.0

    def test_risk_event_adds_pressure(self):
        base = _emotional_bias(1, 2.0, risk_event=False)
        with_risk = _emotional_bias(1, 2.0, risk_event=True)
        assert with_risk > base

    def test_capped_at_one(self):
        assert _emotional_bias(10, 50.0, risk_event=True) <= 1.0


class TestEAFScore:
    def test_perfect_conditions(self):
        eaf = _eaf_score(0.95, 0.0, 0.95, 0.90, 0.8)
        assert eaf >= 0.85

    def test_high_emotion_lowers_eaf(self):
        good = _eaf_score(0.95, 0.0, 0.95, 0.90)
        bad = _eaf_score(0.95, 0.80, 0.95, 0.90)
        assert bad < good

    def test_fundamental_boost(self):
        without = _eaf_score(0.90, 0.10, 0.90, 0.85, fundamental_strength=0.0)
        with_fund = _eaf_score(0.90, 0.10, 0.90, 0.85, fundamental_strength=1.0)
        assert with_fund > without


# ═══════════════════════════════════════════════════════════════════════
# PSYCHOLOGY GATES
# ═══════════════════════════════════════════════════════════════════════

class TestEvaluateGates:
    def test_full_data_scores_correctly(self):
        data = _make_full_gate_data(3)
        result = _evaluate_gates(data)
        assert result["total_score"] > 0
        assert len(result["gates"]) == 10
        assert all(isinstance(g, PsychGate) for g in result["gates"])

    def test_empty_data_scores_zero(self):
        """Missing data must NOT produce perfect score."""
        result = _evaluate_gates({})
        assert result["total_score"] == 0, (
            "Empty gate data should score 0 (fail-safe), not max"
        )

    def test_none_data_scores_zero(self):
        result = _evaluate_gates(None)
        assert result["total_score"] == 0

    def test_critical_gates_pass_with_good_data(self):
        data = _make_full_gate_data(3)
        result = _evaluate_gates(data)
        assert result["critical_gates_pass"] is True

    def test_critical_gates_fail_with_zero(self):
        data = _make_full_gate_data(3)
        # Zero out critical gates (8, 9, 10)
        data["MTA_HIERARCHY"] = {"sequence_correct": 0, "compliance": 0, "no_violations": 0}
        data["BODY_CLOSE_PATIENCE"] = {"h4_discipline": 0, "patience_level": 0, "wait_capability": 0}
        data["DECISION_GATE_FOCUS"] = {"proximity_focus": 0, "precision": 0, "no_mid_range": 0}
        result = _evaluate_gates(data)
        assert result["critical_gates_pass"] is False

    def test_sub_scores_clamped(self):
        data = {"PHYSICAL_STATE": {"sleep_quality": 999, "health_status": -5, "substances_clear": 2}}
        result = _evaluate_gates(data)
        gate = result["gates"][0]
        assert gate.sub_scores["sleep_quality"] == 3  # clamped to max 3
        assert gate.sub_scores["health_status"] == 0  # clamped to min 0
        assert gate.sub_scores["substances_clear"] == 2

    def test_missing_sub_key_tracked(self):
        data = {"PHYSICAL_STATE": {"sleep_quality": 3}}  # missing 2 sub_keys
        result = _evaluate_gates(data)
        gate = result["gates"][0]
        assert len(gate.missing_fields) == 2


# ═══════════════════════════════════════════════════════════════════════
# MAIN ANALYZER — INTEGRATION
# ═══════════════════════════════════════════════════════════════════════

class TestL5AnalysisLayerBasic:
    def test_returns_dict(self, layer, fixed_now):
        result = layer.analyze(pair="EURUSD", now=fixed_now)
        assert isinstance(result, dict)
        assert result["pair"] == "EURUSD"
        assert result["valid"] is True

    def test_all_expected_keys_present(self, layer, fixed_now):
        result = layer.analyze(pair="GBPUSD", now=fixed_now)
        required_keys = [
            "psychology_score", "eaf_score", "emotion_delta", "can_trade",
            "gate_status", "psychology_ok", "fatigue_level", "focus_level",
            "emotional_bias", "discipline_score", "stability_index",
            "fundamental_bias", "fundamental_strength", "sentiment_score",
            "news_count", "impact_level", "risk_event_active",
            "psychology_gates", "critical_gates_pass", "has_gate_data",
            "rgo_governance", "recommendation", "timestamp",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_clean_state_can_trade(self, layer, fixed_now):
        result = layer.analyze(
            pair="GBPUSD",
            news_sentiment=_good_sentiment(),
            session_hours=2.0,
            now=fixed_now,
        )
        assert result["can_trade"] is True
        assert result["gate_status"] == "OPEN"

    def test_risk_event_blocks_trading(self, layer, fixed_now):
        result = layer.analyze(
            pair="GBPUSD",
            news_sentiment=_risk_sentiment(),
            session_hours=2.0,
            now=fixed_now,
        )
        assert result["can_trade"] is False
        assert result["risk_event_active"] is True
        assert "risk_event" in result["recommendation"].lower()


class TestL5StatefulBehavior:
    def test_losses_degrade_score(self, layer, fixed_now):
        clean = layer.analyze(pair="EURUSD", now=fixed_now)
        layer.record_loss()
        layer.record_loss()
        degraded = layer.analyze(pair="EURUSD", now=fixed_now)
        assert degraded["eaf_score"] < clean["eaf_score"]
        assert degraded["psychology_ok"] is False

    def test_win_resets_losses(self, layer, fixed_now):
        layer.record_loss()
        layer.record_loss()
        layer.record_win()
        result = layer.analyze(pair="EURUSD", now=fixed_now)
        assert result["consecutive_losses"] == 0

    def test_drawdown_blocks(self, layer, fixed_now):
        layer.update_drawdown(6.0)
        result = layer.analyze(pair="EURUSD", now=fixed_now)
        assert result["drawdown_ok"] is False
        assert result["can_trade"] is False


class TestL5CrossIntegration:
    def test_risk_event_increases_emotion(self, layer, fixed_now):
        calm = layer.analyze(
            pair="GBPUSD",
            news_sentiment=_good_sentiment(),
            now=fixed_now,
        )
        anxious = layer.analyze(
            pair="GBPUSD",
            news_sentiment=_risk_sentiment(),
            now=fixed_now,
        )
        assert anxious["emotional_bias"] >= calm["emotional_bias"]

    def test_strong_fundamental_boosts_eaf(self, layer, fixed_now):
        weak = layer.analyze(
            pair="GBPUSD",
            news_sentiment={"sentiment_score": 0.0, "news_count": 0, "impact_level": "NONE"},
            now=fixed_now,
        )
        strong = layer.analyze(
            pair="GBPUSD",
            news_sentiment={"sentiment_score": 0.5, "news_count": 5, "impact_level": "HIGH"},
            now=fixed_now,
        )
        # Strong fundamental has higher fundamental_strength → EAF boost
        assert strong["fundamental_strength"] > weak["fundamental_strength"]


class TestL5WithGateData:
    def test_gate_data_included_in_output(self, layer, fixed_now):
        gate_data = _make_full_gate_data(3)
        result = layer.analyze(
            pair="EURUSD", psychology_data=gate_data, now=fixed_now,
        )
        assert result["has_gate_data"] is True
        assert len(result["psychology_gates"]) == 10
        assert result["gate_total_score"] > 0

    def test_no_gate_data_still_works(self, layer, fixed_now):
        result = layer.analyze(pair="EURUSD", now=fixed_now)
        assert result["has_gate_data"] is False
        assert result["critical_gates_pass"] is True  # not penalized

    def test_failed_critical_gates_block(self, layer, fixed_now):
        gate_data = _make_full_gate_data(3)
        gate_data["MTA_HIERARCHY"] = {"sequence_correct": 0, "compliance": 0, "no_violations": 0}
        gate_data["BODY_CLOSE_PATIENCE"] = {"h4_discipline": 0, "patience_level": 0, "wait_capability": 0}
        gate_data["DECISION_GATE_FOCUS"] = {"proximity_focus": 0, "precision": 0, "no_mid_range": 0}
        result = layer.analyze(
            pair="EURUSD", psychology_data=gate_data, now=fixed_now,
        )
        assert result["critical_gates_pass"] is False
        assert "critical_gates" in result["recommendation"].lower()


class TestL5RGOGovernance:
    def test_full_integrity(self, layer, fixed_now):
        result = layer.analyze(
            pair="GBPUSD",
            news_sentiment=_good_sentiment(),
            session_hours=2.0,
            now=fixed_now,
        )
        rgo = result["rgo_governance"]
        assert rgo["integrity_level"] in ("FULL", "PARTIAL", "DEGRADED")
        assert rgo["vault_sync"] in ("SYNCED", "DESYNCED")
        assert isinstance(rgo["lambda_esi_stable"], bool)


# ═══════════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY
# ═══════════════════════════════════════════════════════════════════════

class TestL5PsychologyAnalyzerCompat:
    def test_original_signature_works(self):
        analyzer = L5PsychologyAnalyzer()
        result = analyzer.analyze("EURUSD")
        assert "eaf_score" in result
        assert "can_trade" in result

    def test_stateful_methods(self):
        analyzer = L5PsychologyAnalyzer()
        analyzer.record_loss()
        analyzer.record_win()
        analyzer.update_drawdown(3.0)
        analyzer.reset_session()
        result = analyzer.analyze("GBPUSD")
        assert result["consecutive_losses"] == 0


class TestAnalyzeFundamentalCompat:
    def test_original_signature_works(self, fixed_now):
        result = analyze_fundamental(
            market_data={},
            news_sentiment=_good_sentiment(),
            pair="GBPUSD",
            now=fixed_now,
        )
        assert "fundamental_bias" in result
        assert "fundamental_strength" in result
        assert result["valid"] is True

    def test_no_sentiment_returns_neutral(self, fixed_now):
        result = analyze_fundamental(market_data={}, now=fixed_now)
        assert result["fundamental_bias"] == "NEUTRAL"


class TestAnalyzeL5Convenience:
    def test_works_with_gate_data(self, fixed_now):
        result = analyze_l5(
            pair="EURUSD",
            psychology_data=_make_full_gate_data(3), # type: ignore
            now=fixed_now,
        )
        assert result["has_gate_data"] is True
        assert result["valid"] is True


# ═══════════════════════════════════════════════════════════════════════
# CONSTITUTIONAL COMPLIANCE
# ═══════════════════════════════════════════════════════════════════════

class TestNoSideEffects:
    """Verify L5 is pure analysis — no execution, no mutation outside self."""

    def test_no_execution_fields(self, layer, fixed_now):
        result = layer.analyze(pair="EURUSD", now=fixed_now)
        forbidden = ["lot_size", "order_id", "account_balance", "equity",
                      "execute", "place_order"]
        result_str = str(result)
        for key in forbidden:
            assert key not in result_str, (
                f"Execution-level field '{key}' found in L5 output — "
                "violates constitutional boundary"
            )

    def test_output_is_dict_not_command(self, layer, fixed_now):
        result = layer.analyze(pair="EURUSD", now=fixed_now)
        assert isinstance(result, dict)
        assert "can_trade" in result  # advisory, not execution
        # can_trade is a gate signal, not an order command
