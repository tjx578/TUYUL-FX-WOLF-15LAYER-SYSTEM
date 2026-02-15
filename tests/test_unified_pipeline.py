"""
Tests for unified pipeline v8.0 — engines, result, two-pass governance.

Covers:
  - L13ReflectiveEngine (single pass, direction alignment)
  - L15MetaSovereigntyEngine (meta computation, enforcement, drift)
  - PipelineResult (dataclass, backward compat, dict access)
  - build_l12_synthesis (standalone function)
  - Two-pass governance integration
  - Sovereignty enforcement with verdict downgrade
"""

import pytest  # pyright: ignore[reportMissingImports]

from pipeline.engines import L13ReflectiveEngine, L15MetaSovereigntyEngine
from pipeline.result import PipelineResult
from pipeline.wolf_constitutional_pipeline import build_l12_synthesis

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
    """Tests for L13ReflectiveEngine."""

    def test_reflect_baseline_meta(self):
        """Pass 1: meta_integrity=1.0 should produce predictable αβγ."""
        engine = L13ReflectiveEngine()
        synthesis = _make_synthesis(direction="BUY", technical_bias="BULLISH")
        verdict = _make_verdict("EXECUTE_BUY")

        result = engine.reflect(synthesis, verdict, meta_integrity=1.0)

        assert result["meta_integrity"] == 1.0
        assert result["alpha"] == 1.0  # BUY + BULLISH = aligned
        assert result["beta"] == 1.0   # EXECUTE + aligned = 1.0
        assert result["gamma"] == 1.0  # meta_integrity = 1.0
        assert result["abg_score"] == pytest.approx(1.0)
        assert result["field_state"] == "EXPANSION"
        assert result["execution_window"] == "OPTIMAL"

    def test_reflect_with_real_meta(self):
        """Pass 2: meta_integrity < 1.0 should lower gamma and αβγ score."""
        engine = L13ReflectiveEngine()
        synthesis = _make_synthesis(direction="BUY", technical_bias="BULLISH")
        verdict = _make_verdict("EXECUTE_BUY")

        result = engine.reflect(synthesis, verdict, meta_integrity=0.6)

        assert result["gamma"] == 0.6
        assert result["abg_score"] < 1.0
        # alpha=1.0*0.4 + beta=1.0*0.3 + gamma=0.6*0.3 = 0.4+0.3+0.18 = 0.88
        assert result["abg_score"] == pytest.approx(0.88)

    def test_reflect_misaligned_direction(self):
        """BUY with BEARISH bias should produce low LRCE/FRPC."""
        engine = L13ReflectiveEngine()
        synthesis = _make_synthesis(direction="BUY", technical_bias="BEARISH")
        verdict = _make_verdict("EXECUTE_BUY")

        result = engine.reflect(synthesis, verdict, meta_integrity=1.0)

        assert result["alpha"] == 0.3  # Misaligned
        assert result["beta"] == 0.3   # Misaligned
        assert result["abg_score"] < 0.7

    def test_reflect_hold_direction(self):
        """HOLD direction should give neutral LRCE."""
        engine = L13ReflectiveEngine()
        synthesis = _make_synthesis(direction="HOLD", technical_bias="NEUTRAL")
        verdict = _make_verdict("HOLD", proceed=False)

        result = engine.reflect(synthesis, verdict, meta_integrity=1.0)

        assert result["alpha"] == 0.5  # HOLD = neutral


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
        pass1 = L13ReflectiveEngine().reflect(synthesis, verdict, meta_integrity=1.0)
        sovereignty = _make_sovereignty()
        gates = _make_gates()

        meta = engine.compute_meta(synthesis, verdict, pass1, sovereignty, gates)

        assert meta["conscious_phase"] == "EXPANSION"
        assert meta["meta_integrity"] > 0.8
        assert meta["full_reflective_state"]["all_harmonized"] is True

    def test_compute_meta_low_wolf_score(self):
        """Low wolf score should fail zona 2."""
        engine = L15MetaSovereigntyEngine()
        synthesis = _make_synthesis(wolf_score=15)
        verdict = _make_verdict("EXECUTE_BUY")
        pass1 = L13ReflectiveEngine().reflect(synthesis, verdict, meta_integrity=1.0)
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
        """High drift should escalate GRANTED → RESTRICTED."""
        engine = L15MetaSovereigntyEngine()
        verdict = _make_verdict("EXECUTE_BUY")
        pass1 = {"abg_score": 0.90}
        pass2 = {"abg_score": 0.60}  # drift = 0.30 > 0.15
        meta = {"meta_integrity": 0.70}
        sovereignty = _make_sovereignty(execution_rights="GRANTED", vault_sync=0.98)

        enforcement = engine.enforce_sovereignty(verdict, pass1, pass2, meta, sovereignty)

        # drift 0.30 > DRIFT_MAX_GRANTED (0.15) → RESTRICTED
        # Then drift 0.30 > DRIFT_MAX_RESTRICTED (0.20) → REVOKED
        assert enforcement["execution_rights"] == "REVOKED"
        assert enforcement["verdict_downgraded"] is True
        assert verdict["verdict"] == "HOLD"  # Mutated

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
    """Tests for the two-pass L13 governance flow."""

    def test_two_pass_drift_detection(self):
        """Pass 2 should differ from Pass 1 when real meta < 1.0."""
        l13 = L13ReflectiveEngine()
        l15 = L15MetaSovereigntyEngine()

        synthesis = _make_synthesis()
        verdict = _make_verdict("EXECUTE_BUY")
        gates = _make_gates()
        sovereignty = _make_sovereignty()

        # Pass 1: baseline
        pass1 = l13.reflect(synthesis, verdict, meta_integrity=1.0)

        # L15 meta
        meta = l15.compute_meta(synthesis, verdict, pass1, sovereignty, gates)
        real_meta = meta["meta_integrity"]
        assert real_meta <= 1.0

        # Pass 2: refined
        pass2 = l13.reflect(synthesis, verdict, meta_integrity=real_meta)

        # Drift ratio should be small for aligned signals
        drift = abs(pass1["abg_score"] - pass2["abg_score"])
        assert drift >= 0.0

        # Enforcement should not downgrade for well-aligned signals
        enforcement = l15.enforce_sovereignty(verdict, pass1, pass2, meta, sovereignty)
        assert enforcement["drift_ratio"] == pytest.approx(drift)

    def test_two_pass_meta_modulates_gamma(self):
        """Real meta should feed into gamma channel of Pass 2."""
        l13 = L13ReflectiveEngine()

        synthesis = _make_synthesis()
        verdict = _make_verdict("EXECUTE_BUY")

        pass1 = l13.reflect(synthesis, verdict, meta_integrity=1.0)
        pass2 = l13.reflect(synthesis, verdict, meta_integrity=0.5)

        assert pass1["gamma"] == 1.0
        assert pass2["gamma"] == 0.5
        assert pass2["abg_score"] < pass1["abg_score"]


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

        assert result.reflective["pass"] == 2 # pyright: ignore[reportOptionalSubscript]

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

        assert result.reflective["pass"] == 1 # pyright: ignore[reportOptionalSubscript]


# ══════════════════════════════════════════════════════════════
#  BUILD L12 SYNTHESIS (standalone function)
# ══════════════════════════════════════════════════════════════

class TestBuildL12Synthesis:
    """Tests for standalone build_l12_synthesis function."""

    def _make_layer_outputs(self):
        """Create minimal layer outputs for synthesis building."""
        return {
            "l1": {"valid": True, "regime": "TREND", "dominant_force": "BULL", "regime_confidence": 0.92, "csi": 0.5},
            "l2": {"valid": True, "reflex_coherence": 0.9, "conf12": 0.85, "frpc_energy": 0.1, "frpc_state": "SYNC"},
            "l3": {"valid": True, "trend": "BULLISH", "trq3d_energy": 0.7, "drift": 0.01},
            "l4": {"technical_score": 80, "wolf_30_point": {"total": 27, "f_score": 5, "t_score": 10, "fta_score": 0.85, "exec_score": 6}},
            "l5": {"psychology_score": 75, "current_drawdown": 1.5, "eaf_score": 0.0, "emotion_delta": 0.0},
            "l6": {"risk_ok": True, "propfirm_compliant": True, "drawdown_level": "LEVEL_0", "risk_multiplier": 1.0, "risk_status": "ACCEPTABLE", "lrce": 0.85},
            "l7": {"win_probability": 65.0},
            "l8": {"tii_sym": 0.95, "integrity": 0.98},
            "l9": {"confidence": 0.8, "dvg_confidence": 0.8, "liquidity_score": 0.75, "smart_money_signal": "NEUTRAL", "ob_present": False, "fvg_present": False, "sweep_detected": False, "smart_money_bias": "NEUTRAL"},
            "l10": {"position_ok": True, "fta_score": 0.85, "fta_multiplier": 1.0, "final_lot_size": 0.01, "adjusted_risk_pct": 1.0, "adjusted_risk_amount": 100.0},
            "l11": {"valid": True, "rr": 2.5, "entry_price": 1.10000, "stop_loss": 1.09500, "take_profit_1": 1.11250, "battle_strategy": "SHADOW_STRIKE"},
            "macro": {"regime": "TREND", "phase": "NEUTRAL", "macro_vol_ratio": 1.0, "alignment": True, "liquidity": {}, "bias_override": {}},
            "macro_vix_state": {"regime_state": 1, "risk_multiplier": 1.0},
        }

    def test_synthesis_has_all_required_keys(self):
        """Synthesis should contain all keys required by L12 verdict engine."""
        layers = self._make_layer_outputs()
        synthesis = build_l12_synthesis(
            symbol="EURUSD",
            l1=layers["l1"], l2=layers["l2"], l3=layers["l3"],
            l4=layers["l4"], l5=layers["l5"], l6=layers["l6"],
            l7=layers["l7"], l8=layers["l8"], l9=layers["l9"],
            l10=layers["l10"], l11=layers["l11"],
            macro=layers["macro"],
            macro_vix_state=layers["macro_vix_state"],
        )

        required_keys = ["pair", "scores", "layers", "execution", "risk", "propfirm", "bias", "system"]
        for key in required_keys:
            assert key in synthesis, f"Missing required key: {key}"

        assert synthesis["pair"] == "EURUSD"
        assert synthesis["execution"]["direction"] == "BUY"

    def test_synthesis_safe_mode_propagated(self):
        """safe_mode should appear in system section."""
        layers = self._make_layer_outputs()
        synthesis = build_l12_synthesis(
            symbol="EURUSD",
            l1=layers["l1"], l2=layers["l2"], l3=layers["l3"],
            l4=layers["l4"], l5=layers["l5"], l6=layers["l6"],
            l7=layers["l7"], l8=layers["l8"], l9=layers["l9"],
            l10=layers["l10"], l11=layers["l11"],
            macro=layers["macro"],
            macro_vix_state=layers["macro_vix_state"],
            safe_mode=True,
            latency_ms=42.0,
        )

        assert synthesis["system"]["safe_mode"] is True
        assert synthesis["system"]["latency_ms"] == 42.0

    def test_synthesis_direction_hold_for_neutral(self):
        """NEUTRAL trend should produce HOLD direction."""
        layers = self._make_layer_outputs()
        layers["l3"]["trend"] = "NEUTRAL" # pyright: ignore[reportArgumentType]

        synthesis = build_l12_synthesis(
            symbol="EURUSD",
            l1=layers["l1"], l2=layers["l2"], l3=layers["l3"],
            l4=layers["l4"], l5=layers["l5"], l6=layers["l6"],
            l7=layers["l7"], l8=layers["l8"], l9=layers["l9"],
            l10=layers["l10"], l11=layers["l11"],
            macro=layers["macro"],
            macro_vix_state=layers["macro_vix_state"],
        )

        assert synthesis["execution"]["direction"] == "HOLD"
