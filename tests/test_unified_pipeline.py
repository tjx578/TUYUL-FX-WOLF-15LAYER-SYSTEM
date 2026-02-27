"""
Tests for unified pipeline v8.0 -- engines, result, two-pass governance.

Covers:
  - L13ReflectiveEngine (single pass, direction alignment, probability calibration)
  - L15MetaSovereigntyEngine (meta computation, enforcement, drift)
  - PipelineResult (dataclass, backward compat, dict access)
  - build_l12_synthesis (module-level function with layer_results dict)
  - Two-pass governance integration
  - Sovereignty enforcement with verdict downgrade
  - _timed_call per-layer timeout
  - Macro analyzer wiring (MonthlyRegimeAnalyzer + MacroVolatilityEngine)
"""

import time

import pytest  # pyright: ignore[reportMissingImports]

from pipeline.engines import L13ReflectiveEngine, L15MetaSovereigntyEngine
from pipeline.result import PipelineResult
from pipeline.wolf_constitutional_pipeline import (
    WolfConstitutionalPipeline,
    _LAYER_TIMEOUT_SEC,
    build_l12_synthesis,
)

# ══════════════════════════════════════════════════════════════
#  FIXTURES
# ══════════════════════════════════════════════════════════════

def _make_synthesis(
    direction: str = "BUY",
    technical_bias: str = "BULLISH",
    rr: float = 2.5,
    tii: float = 0.95,
    integrity: float = 0.98,
    wolf_score: int = 27,
) -> dict:
    """Build a minimal synthesis dict for testing."""
    return {
        "pair": "EURUSD",
        "scores": {
            "wolf_30_point": wolf_score,
            "f_score": 5,
            "t_score": 10,
            "fta_score": 0.85,
            "fta_multiplier": 1.0,
            "exec_score": 6,
            "psychology_score": 75,
            "technical_score": 80,
        },
        "layers": {
            "L1_context_coherence": 0.92,
            "L2_reflex_coherence": 0.90,
            "L3_trq3d_energy": 0.70,
            "L7_monte_carlo_win": 0.65,
            "L8_tii_sym": tii,
            "L8_integrity_index": integrity,
            "L9_dvg_confidence": 0.80,
            "L9_liquidity_score": 0.75,
            "conf12": 0.85,
        },
        "execution": {
            "direction": direction,
            "entry_price": 1.10000,
            "stop_loss": 1.09500,
            "take_profit_1": 1.11250,
            "entry_zone": "1.09900-1.10000",
            "execution_mode": "TP1_ONLY",
            "battle_strategy": "SHADOW_STRIKE",
            "rr_ratio": rr,
            "lot_size": 0.01,
            "risk_percent": 1.0,
            "risk_amount": 100.0,
            "slippage_estimate": 0.0,
            "optimal_timing": "",
        },
        "risk": {
            "current_drawdown": 1.5,
            "drawdown_level": "LEVEL_0",
            "risk_multiplier": 1.0,
            "risk_status": "ACCEPTABLE",
            "lrce": 0.85,
        },
        "propfirm": {
            "compliant": True,
            "daily_loss_status": "OK",
            "max_drawdown_status": "OK",
            "profit_target_progress": 0.0,
        },
        "bias": {
            "fundamental": "NEUTRAL",
            "technical": technical_bias,
            "macro": "TREND",
        },
        "cognitive": {"regime": "TREND", "dominant_force": "NEUTRAL", "cbv": 0.0, "csi": 0.0},
        "fusion_frpc": {"conf12": 0.85, "frpc_energy": 0.0, "lambda_esi": 0.003, "integrity": integrity},
        "trq3d": {"alpha": 0.0, "beta": 0.0, "gamma": 0.0, "drift": 0.02, "mean_energy": 0.7, "intensity": 0.0},
        "smc": {"structure": "RANGE", "smart_money_signal": "NEUTRAL", "liquidity_zone": "0.00000", "ob_present": False, "fvg_present": False, "sweep_detected": False, "bias": "NEUTRAL"},
        "wolf_discipline": {"score": wolf_score / 30.0, "polarity_deviation": 0.0, "lambda_balance": "ACTIVE", "bias_symmetry": "NEUTRAL", "eaf_score": 0.0, "emotional_state": "CALM"},
        "macro": {"regime": "TREND", "phase": "NEUTRAL", "volatility_ratio": 1.0, "mn_aligned": False, "liquidity": {}, "bias_override": {}},
        "macro_vix": {"regime_state": 1, "risk_multiplier": 1.0},
        "system": {"latency_ms": 50.0, "safe_mode": False},
    }


def _make_verdict(verdict: str = "EXECUTE_BUY", proceed: bool = True) -> dict:
    return {
        "verdict": verdict,
        "confidence": "HIGH",
        "wolf_status": "PACK",
        "gates": {"passed": 10, "total": 10},
        "proceed_to_L13": proceed,
    }


def _make_gates(total_passed: int = 9) -> dict:
    return {
        "total_passed": total_passed,
        "total_gates": 9,
        "gate_1_tii": "PASS",
        "gate_2_montecarlo": "PASS",
        "gate_3_frpc": "PASS",
        "gate_4_conf12": "PASS",
        "gate_5_rr": "PASS",
        "gate_6_integrity": "PASS",
        "gate_7_propfirm": "PASS",
        "gate_8_drawdown": "PASS",
        "gate_9_latency": "PASS",
    }


def _make_sovereignty(execution_rights: str = "GRANTED", vault_sync: float = 1.0) -> dict:
    return {
        "execution_rights": execution_rights,
        "lot_multiplier": 1.0 if execution_rights == "GRANTED" else 0.5,
        "vault_sync": vault_sync,
        "feed_freshness": 1.0,
        "redis_health": 1.0,
        "meta_integrity": vault_sync,
    }


# ══════════════════════════════════════════════════════════════
#  L13 REFLECTIVE ENGINE
# ══════════════════════════════════════════════════════════════

class TestL13ReflectiveEngine:
    """Tests for L13ReflectiveEngine.reflect(symbol, historical_verdicts, current_layer_results).

    Note: The current reflect() implementation hardcodes
    ``l12_verdict = HOLD`` and ``meta_integrity = 1.0`` internally.
    FRPC therefore always evaluates under a HOLD verdict, and gamma
    is always 1.0 regardless of caller input.
    """

    def test_reflect_aligned_direction(self):
        """BUY + BULLISH bias: LRCE=1.0, FRPC=0.5 (HOLD+non-neutral), gamma=1.0."""
        engine = L13ReflectiveEngine()
        synthesis = _make_synthesis(direction="BUY", technical_bias="BULLISH")

        result = engine.reflect(
            symbol="EURUSD",
            historical_verdicts=[],
            current_layer_results=synthesis,
        )

        assert result["meta_integrity"] == 1.0
        assert result["gamma"] == 1.0       # hardcoded meta_integrity
        assert result["alpha"] == 1.0       # BUY + BULLISH = aligned -> LRCE 1.0
        assert result["beta"] == 0.5        # HOLD + BULLISH -> 0.5
        # abg = 1.0*0.4 + 0.5*0.3 + 1.0*0.3 = 0.85
        assert result["abg_score"] == pytest.approx(0.85)
        assert result["field_state"] == "EXPANSION"
        assert result["execution_window"] == "OPTIMAL"

    def test_reflect_neutral_bias(self):
        """BUY + NEUTRAL bias: LRCE=0.7, FRPC=0.8 (HOLD+neutral), gamma=1.0."""
        engine = L13ReflectiveEngine()
        synthesis = _make_synthesis(direction="BUY", technical_bias="NEUTRAL")

        result = engine.reflect("EURUSD", [], synthesis)

        assert result["alpha"] == 0.7       # BUY + NEUTRAL -> 0.7
        assert result["beta"] == 0.8        # HOLD + NEUTRAL -> 0.8
        # abg = 0.7*0.4 + 0.8*0.3 + 1.0*0.3 = 0.82
        assert result["abg_score"] == pytest.approx(0.82)
        assert result["field_state"] == "EXPANSION"
        assert result["execution_window"] == "GOOD"

    def test_reflect_misaligned_direction(self):
        """BUY + BEARISH bias should produce low LRCE (alpha=0.3)."""
        engine = L13ReflectiveEngine()
        synthesis = _make_synthesis(direction="BUY", technical_bias="BEARISH")

        result = engine.reflect("EURUSD", [], synthesis)

        assert result["alpha"] == 0.3       # Misaligned
        assert result["beta"] == 0.5        # HOLD + BEARISH -> 0.5
        # abg = 0.3*0.4 + 0.5*0.3 + 1.0*0.3 = 0.57
        assert result["abg_score"] == pytest.approx(0.57)
        assert result["field_state"] == "COMPRESSION"
        assert result["execution_window"] == "POOR"

    def test_reflect_hold_direction(self):
        """HOLD direction should give neutral LRCE (alpha=0.5)."""
        engine = L13ReflectiveEngine()
        synthesis = _make_synthesis(direction="HOLD", technical_bias="NEUTRAL")

        result = engine.reflect("EURUSD", [], synthesis)

        assert result["alpha"] == 0.5       # HOLD -> 0.5
        assert result["beta"] == 0.8        # HOLD + NEUTRAL -> 0.8
        # abg = 0.5*0.4 + 0.8*0.3 + 1.0*0.3 = 0.74
        assert result["abg_score"] == pytest.approx(0.74)
        assert result["field_state"] == "COMPRESSION"  # 0.74 < 0.80
        assert result["execution_window"] == "GOOD"     # 0.74 >= 0.70

    def test_reflect_probability_calibration_insufficient(self):
        """Empty historical_verdicts should produce N/A calibration grade."""
        engine = L13ReflectiveEngine()
        synthesis = _make_synthesis()

        result = engine.reflect("EURUSD", [], synthesis)

        cal = result["probability_calibration"]
        assert cal["calibration_grade"] == "N/A"
        assert cal["sample_size"] == 0
        assert "insufficient_samples" in cal.get("note", "")

    def test_reflect_ror_trend_unknown_when_few_samples(self):
        """Risk-of-ruin trend should be UNKNOWN with < 3 history items."""
        engine = L13ReflectiveEngine()
        # Two verdicts with ror -- still not enough for trend
        verdicts = [
            {"probability_context": {"risk_of_ruin": 0.10}},
            {"probability_context": {"risk_of_ruin": 0.12}},
        ]

        result = engine.reflect("EURUSD", verdicts, _make_synthesis())

        ror = result["risk_of_ruin_trend"]
        assert ror["ror_trend"] == "UNKNOWN"
        assert ror["sample_size"] == 2


# ══════════════════════════════════════════════════════════════
#  L15 META SOVEREIGNTY ENGINE
# ══════════════════════════════════════════════════════════════

class TestL15MetaSovereigntyEngine:
    """Tests for L15MetaSovereigntyEngine."""

    def test_compute_meta_all_pass(self):
        """All zonas passing should produce EXPANSION state."""
        engine = L15MetaSovereigntyEngine()
        synthesis = _make_synthesis()
        verdict = _make_verdict("EXECUTE_BUY")
        # Obtain pass1 via correct API
        pass1 = L13ReflectiveEngine().reflect("EURUSD", [], synthesis)
        sovereignty = _make_sovereignty()
        gates = _make_gates()

        meta = engine.compute_meta(synthesis, verdict, pass1, sovereignty, gates)

        assert meta["conscious_phase"] == "EXPANSION"
        # meta_integrity = abg*0.4 + vault*0.3 + frpc*0.2 + integrity*0.1
        #                = 0.85*0.4 + 1.0*0.3 + 0.5*0.2 + 0.98*0.1 ~ 0.838
        assert meta["meta_integrity"] > 0.8
        assert meta["full_reflective_state"]["all_harmonized"] is True
        assert meta["full_reflective_state"]["achieved"] is True

    def test_compute_meta_low_wolf_score(self):
        """Low wolf score should fail zona 2 (confluence_scoring)."""
        engine = L15MetaSovereigntyEngine()
        synthesis = _make_synthesis(wolf_score=15)
        verdict = _make_verdict("EXECUTE_BUY")
        pass1 = L13ReflectiveEngine().reflect("EURUSD", [], synthesis)
        sovereignty = _make_sovereignty()
        gates = _make_gates()

        meta = engine.compute_meta(synthesis, verdict, pass1, sovereignty, gates)

        assert meta["zona_health"]["confluence_scoring"]["status"] == "FAIL"
        assert meta["conscious_phase"] == "STABILIZATION"
        assert meta["full_reflective_state"]["all_harmonized"] is False

    def test_enforce_sovereignty_granted(self):
        """GRANTED should stay GRANTED when vault sync is high and drift is low."""
        engine = L15MetaSovereigntyEngine()
        verdict = _make_verdict("EXECUTE_BUY")
        pass1 = {"abg_score": 0.90}
        pass2 = {"abg_score": 0.88}  # drift = 0.02
        meta = {"meta_integrity": 0.95}
        sovereignty = _make_sovereignty(execution_rights="GRANTED", vault_sync=1.0)

        enforcement = engine.enforce_sovereignty(verdict, pass1, pass2, meta, sovereignty)

        assert enforcement["execution_rights"] == "GRANTED"
        assert enforcement["verdict_downgraded"] is False
        assert enforcement["drift_ratio"] == pytest.approx(0.02)

    def test_enforce_sovereignty_drift_downgrade(self):
        """High drift should escalate GRANTED -> RESTRICTED -> REVOKED."""
        engine = L15MetaSovereigntyEngine()
        verdict = _make_verdict("EXECUTE_BUY")
        pass1 = {"abg_score": 0.90}
        pass2 = {"abg_score": 0.60}  # drift = 0.30 > both thresholds
        meta = {"meta_integrity": 0.70}
        # vault_sync=0.98 < VAULT_SYNC_MIN_GRANTED(0.985) -> RESTRICTED
        # then drift 0.30 > DRIFT_MAX_RESTRICTED(0.20) -> REVOKED
        sovereignty = _make_sovereignty(execution_rights="GRANTED", vault_sync=0.98)

        enforcement = engine.enforce_sovereignty(verdict, pass1, pass2, meta, sovereignty)

        assert enforcement["execution_rights"] == "REVOKED"
        assert enforcement["verdict_downgraded"] is True
        assert verdict["verdict"] == "HOLD"  # Mutated in-place

    def test_enforce_sovereignty_revoked_downgrades_verdict(self):
        """REVOKED sovereignty must downgrade EXECUTE verdict to HOLD."""
        engine = L15MetaSovereigntyEngine()
        verdict = _make_verdict("EXECUTE_SELL")
        pass1 = {"abg_score": 0.50}
        pass2 = {"abg_score": 0.50}
        meta = {"meta_integrity": 0.40}
        sovereignty = _make_sovereignty(execution_rights="REVOKED", vault_sync=0.5)

        enforcement = engine.enforce_sovereignty(verdict, pass1, pass2, meta, sovereignty)

        assert enforcement["execution_rights"] == "REVOKED"
        assert enforcement["verdict_downgraded"] is True
        assert verdict["verdict"] == "HOLD"
        assert verdict["confidence"] == "LOW"

    def test_enforce_sovereignty_hold_not_downgraded(self):
        """A HOLD verdict should not be flagged as downgraded."""
        engine = L15MetaSovereigntyEngine()
        verdict = _make_verdict("HOLD", proceed=False)
        sovereignty = _make_sovereignty(execution_rights="REVOKED", vault_sync=0.5)

        enforcement = engine.enforce_sovereignty(verdict, None, None, {}, sovereignty)

        assert enforcement["verdict_downgraded"] is False


# ══════════════════════════════════════════════════════════════
#  TWO-PASS GOVERNANCE INTEGRATION
# ══════════════════════════════════════════════════════════════

class TestTwoPassGovernance:
    """Tests for the two-pass L13 governance flow.

    Note: Because reflect() hardcodes meta_integrity=1.0 internally,
    two passes with the *same* synthesis yield identical output (zero
    drift).  Real two-pass drift is simulated by varying the synthesis
    between passes.
    """

    def test_two_pass_consistent_for_same_input(self):
        """Same synthesis should produce zero drift between passes."""
        l13 = L13ReflectiveEngine()
        l15 = L15MetaSovereigntyEngine()

        synthesis = _make_synthesis()
        verdict = _make_verdict("EXECUTE_BUY")
        gates = _make_gates()
        sovereignty = _make_sovereignty()

        # Pass 1: baseline
        pass1 = l13.reflect("EURUSD", [], synthesis)

        # L15 meta (uses Pass 1)
        meta = l15.compute_meta(synthesis, verdict, pass1, sovereignty, gates)
        real_meta = meta["meta_integrity"]
        assert real_meta <= 1.0

        # Pass 2: same synthesis -> identical result
        pass2 = l13.reflect("EURUSD", [], synthesis)

        assert pass1["abg_score"] == pytest.approx(pass2["abg_score"])

        # Enforcement with zero drift should not downgrade
        enforcement = l15.enforce_sovereignty(verdict, pass1, pass2, meta, sovereignty)
        assert enforcement["drift_ratio"] == pytest.approx(0.0)
        assert enforcement["verdict_downgraded"] is False

    def test_two_pass_different_synthesis_produces_drift(self):
        """Varying synthesis between passes should produce measurable drift."""
        l13 = L13ReflectiveEngine()
        l15 = L15MetaSovereigntyEngine()

        aligned = _make_synthesis(direction="BUY", technical_bias="BULLISH")
        misaligned = _make_synthesis(direction="BUY", technical_bias="BEARISH")

        pass1 = l13.reflect("EURUSD", [], aligned)       # abg ~ 0.85
        pass2 = l13.reflect("EURUSD", [], misaligned)    # abg ~ 0.57

        assert pass1["abg_score"] > pass2["abg_score"]
        drift = abs(pass1["abg_score"] - pass2["abg_score"])
        assert drift > 0.1  # Significant drift

        # Verify enforcement detects the drift
        verdict = _make_verdict("EXECUTE_BUY")
        meta = {"meta_integrity": 0.80}
        sovereignty = _make_sovereignty(execution_rights="GRANTED", vault_sync=0.98)
        enforcement = l15.enforce_sovereignty(verdict, pass1, pass2, meta, sovereignty)

        # vault_sync=0.98 < 0.985 -> RESTRICTED, drift > 0.20 -> REVOKED
        assert enforcement["execution_rights"] == "REVOKED"
        assert enforcement["drift_ratio"] == pytest.approx(drift)


# ══════════════════════════════════════════════════════════════
#  PIPELINE RESULT
# ══════════════════════════════════════════════════════════════

class TestPipelineResult:
    """Tests for PipelineResult dataclass."""

    def test_to_dict_backward_compatible(self):
        """Result should convert to dict with all expected keys."""
        result = PipelineResult(
            schema="v8.0",
            pair="EURUSD",
            timestamp="2026-02-15T00:00:00",
            synthesis={"pair": "EURUSD"},
            l12_verdict={"verdict": "HOLD"},
        )

        d = result.to_dict()
        assert d["schema"] == "v8.0"
        assert d["pair"] == "EURUSD"
        assert d["synthesis"]["pair"] == "EURUSD"
        assert d["l12_verdict"]["verdict"] == "HOLD"
        assert d["reflective"] is None  # No passes
        assert d["reflective_pass1"] is None
        assert d["reflective_pass2"] is None

    def test_dict_style_access(self):
        """PipelineResult should support dict-style access."""
        result = PipelineResult(
            schema="v8.0",
            pair="XAUUSD",
            timestamp="2026-02-15T00:00:00",
            synthesis={"pair": "XAUUSD"},
            l12_verdict={"verdict": "EXECUTE_BUY"},
        )

        assert result["pair"] == "XAUUSD"
        assert "synthesis" in result
        assert result.get("nonexistent", "default") == "default"

    def test_reflective_property_prefers_pass2(self):
        """The reflective property should prefer pass2 over pass1."""
        result = PipelineResult(
            schema="v8.0",
            pair="EURUSD",
            timestamp="2026-02-15T00:00:00",
            synthesis={},
            l12_verdict={},
            reflective_pass1={"abg_score": 0.90, "pass": 1},
            reflective_pass2={"abg_score": 0.85, "pass": 2},
        )

        assert result.reflective["pass"] == 2  # pyright: ignore[reportOptionalSubscript]

    def test_reflective_property_fallback_to_pass1(self):
        """When pass2 is None, reflective should return pass1."""
        result = PipelineResult(
            schema="v8.0",
            pair="EURUSD",
            timestamp="2026-02-15T00:00:00",
            synthesis={},
            l12_verdict={},
            reflective_pass1={"abg_score": 0.90, "pass": 1},
            reflective_pass2=None,
        )

        assert result.reflective["pass"] == 1  # pyright: ignore[reportOptionalSubscript]


# ══════════════════════════════════════════════════════════════
#  BUILD L12 SYNTHESIS (module-level function)
# ══════════════════════════════════════════════════════════════

class TestBuildL12Synthesis:
    """Tests for build_l12_synthesis(layer_results).

    The function is module-level.
    ``layer_results`` is a dict keyed by uppercase layer names:
    "L1", "L2", ..., "L11", "macro", "macro_vix_state".
    """

    def _make_layer_results(self) -> dict:
        """Create layer_results dict with uppercase keys matching build_l12_synthesis."""
        return {
            "L1": {
                "valid": True, "regime": "TREND", "dominant_force": "BULL",
                "regime_confidence": 0.92, "csi": 0.5,
            },
            "L2": {
                "valid": True, "reflex_coherence": 0.9, "conf12": 0.85,
                "frpc_energy": 0.1, "frpc_state": "SYNC",
            },
            "L3": {
                "valid": True, "trend": "BULLISH", "trq3d_energy": 0.7, "drift": 0.01,
            },
            # No wolf_30_point dict -- avoids the unbound technical_score path
            # in the if-branch.  The else-branch computes wolf_30_point from
            # technical_score and L7 win_probability.
            "L4": {"technical_score": 80},
            "L5": {
                "psychology_score": 75, "current_drawdown": 1.5,
                "eaf_score": 0.0, "emotion_delta": 0.0,
            },
            "L6": {
                "risk_ok": True, "propfirm_compliant": True,
                "drawdown_level": "LEVEL_0", "risk_multiplier": 1.0,
                "risk_status": "ACCEPTABLE", "lrce": 0.85,
            },
            "L7": {
                "win_probability": 65.0, "bayesian_posterior": 0.62,
                "bayesian_ci_low": 0.45, "bayesian_ci_high": 0.78,
                "mc_passed_threshold": True, "risk_of_ruin": 0.05,
                "validation": "PASS",
            },
            "L8": {"tii_sym": 0.95, "integrity": 0.98},
            "L9": {
                "confidence": 0.8, "dvg_confidence": 0.8, "liquidity_score": 0.75,
                "smart_money_signal": "NEUTRAL", "ob_present": False,
                "fvg_present": False, "sweep_detected": False,
                "smart_money_bias": "NEUTRAL",
            },
            "L10": {
                "position_ok": True, "fta_score": 0.85, "fta_multiplier": 1.0,
                "final_lot_size": 0.01, "adjusted_risk_pct": 1.0,
                "adjusted_risk_amount": 100.0,
            },
            "L11": {
                "valid": True, "rr": 2.5, "entry_price": 1.10000,
                "stop_loss": 1.09500, "take_profit_1": 1.11250,
                "battle_strategy": "SHADOW_STRIKE",
            },
            "macro": "TREND",
            "macro_vix_state": {"regime_state": 1, "risk_multiplier": 1.0},
        }

    def test_synthesis_has_all_required_keys(self):
        """Synthesis should contain all keys required by L12 verdict engine."""
        layer_results = self._make_layer_results()

        synthesis = build_l12_synthesis(layer_results)

        required_keys = [
            "scores", "layers", "execution", "risk",
            "propfirm", "bias", "system",
        ]
        for key in required_keys:
            assert key in synthesis, f"Missing required key: {key}"

        # Direction derived from L3.trend = BULLISH -> BUY
        assert synthesis["execution"]["direction"] == "BUY"

    def test_synthesis_execution_details(self):
        """Execution section should carry through L11 and L10 values."""
        layer_results = self._make_layer_results()
        synthesis = build_l12_synthesis(layer_results)

        assert synthesis["execution"]["entry_price"] == 1.10000
        assert synthesis["execution"]["stop_loss"] == 1.09500
        assert synthesis["execution"]["take_profit_1"] == 1.11250
        assert synthesis["execution"]["rr_ratio"] == 2.5
        assert synthesis["execution"]["lot_size"] == 0.01
        assert synthesis["execution"]["battle_strategy"] == "SHADOW_STRIKE"
        # System defaults (overwritten by pipeline after call)
        assert synthesis["system"]["safe_mode"] is False
        assert synthesis["system"]["latency_ms"] == 0.0

    def test_synthesis_direction_hold_for_neutral(self):
        """NEUTRAL trend should produce HOLD direction."""
        layer_results = self._make_layer_results()
        layer_results["L3"]["trend"] = "NEUTRAL"

        synthesis = build_l12_synthesis(layer_results)

        assert synthesis["execution"]["direction"] == "HOLD"

    def test_macro_regime_fields_in_synthesis(self):
        """MonthlyRegimeAnalyzer fields should flow into synthesis['macro']."""
        layer_results = self._make_layer_results()
        # Simulate a full MonthlyRegimeAnalyzer result being flattened into
        # layer_results_combined (as done in Phase 5 of the pipeline).
        layer_results["macro"] = "BULLISH_EXPANSION"
        layer_results["phase"] = "EXPANSION"
        layer_results["macro_vol_ratio"] = 1.35
        layer_results["alignment"] = True
        layer_results["liquidity"] = {"macro_buy_liquidity": 1.09500}
        layer_results["bias_override"] = {
            "active": True,
            "penalized_direction": "SELL",
            "confidence_multiplier": 0.7,
        }

        synthesis = build_l12_synthesis(layer_results)

        assert synthesis["macro"]["regime"] == "BULLISH_EXPANSION"
        assert synthesis["macro"]["phase"] == "EXPANSION"
        assert synthesis["macro"]["volatility_ratio"] == pytest.approx(1.35)
        assert synthesis["macro"]["mn_aligned"] is True
        assert synthesis["macro"]["bias_override"]["active"] is True

    def test_macro_vix_state_in_synthesis(self):
        """macro_vix_state should flow into synthesis['macro_vix']."""
        layer_results = self._make_layer_results()
        layer_results["macro_vix_state"] = {
            "regime_state": 2,
            "risk_multiplier": 0.3,
            "vix_level": 28.5,
        }

        synthesis = build_l12_synthesis(layer_results)

        assert synthesis["macro_vix"]["regime_state"] == 2
        assert synthesis["macro_vix"]["risk_multiplier"] == pytest.approx(0.3)


# ══════════════════════════════════════════════════════════════
#  _TIMED_CALL PER-LAYER TIMEOUT
# ══════════════════════════════════════════════════════════════

class TestTimedCallTimeout:
    """Tests for WolfConstitutionalPipeline._timed_call per-layer timeout."""

    def test_timed_call_completes_fast_function(self):
        """A function that completes within the timeout should return normally."""
        def fast_fn(x):
            return x * 2

        result = WolfConstitutionalPipeline._timed_call(
            fast_fn, "TEST_LAYER", "EURUSD", 21
        )

        assert result == 42

    def test_timed_call_raises_timeout_error_when_layer_hangs(self, monkeypatch):
        """A function that sleeps longer than the timeout must raise TimeoutError."""
        import pipeline.wolf_constitutional_pipeline as _pipeline_mod

        # Use a very short timeout so the test completes quickly.
        monkeypatch.setattr(_pipeline_mod, "_LAYER_TIMEOUT_SEC", 0.1)

        def hanging_fn():
            time.sleep(1)  # longer than 0.1s, shorter than default 10s

        with pytest.raises(TimeoutError, match="timeout"):
            WolfConstitutionalPipeline._timed_call(
                hanging_fn, "HANGING_LAYER", "EURUSD"
            )

    def test_layer_timeout_constant_is_positive(self):
        """_LAYER_TIMEOUT_SEC must be a positive float."""
        assert _LAYER_TIMEOUT_SEC > 0
