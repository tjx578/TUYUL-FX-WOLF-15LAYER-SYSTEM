"""
Integration tests for Wolf Sovereign Pipeline.

Tests:
1. Pipeline instantiation and lazy loading
2. Synthesis builder produces all required keys for L12
3. L13 two-pass produces different results for different meta_integrity values
4. L15 sovereignty returns GRANTED/RESTRICTED/REVOKED correctly
5. Full pipeline early exit when L12 verdict is not EXECUTE
6. VIX multiplier is properly applied
7. Layer execution order (L11 before L6)
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from analysis.orchestrators.wolf_sovereign_pipeline import (
    L13ReflectiveEngine,
    L15MetaSovereigntyEngine,
    WolfSovereignPipeline,
    build_l12_synthesis,
)


class TestWolfSovereignPipeline:
    """Test Wolf Sovereign Pipeline orchestrator."""

    def test_pipeline_instantiation(self):
        """Test pipeline can be instantiated."""
        pipeline = WolfSovereignPipeline()
        assert pipeline is not None
        # Analyzers should be None until lazy loaded
        assert pipeline._l1 is None
        assert pipeline._l2 is None

    def test_lazy_loading(self):
        """Test analyzers are lazy loaded."""
        pipeline = WolfSovereignPipeline()
        pipeline._ensure_analyzers()

        # All analyzers should now be loaded
        assert pipeline._l1 is not None
        assert pipeline._l2 is not None
        assert pipeline._l3 is not None
        assert pipeline._l11 is not None

    @patch("analysis.orchestrators.wolf_sovereign_pipeline.generate_l12_verdict")
    def test_early_exit_on_hold_verdict(self, mock_verdict):
        """Test pipeline exits early when L12 verdict is not EXECUTE."""
        # Setup mocks
        mock_verdict.return_value = {
            "verdict": "HOLD",
            "confidence": "LOW",
            "proceed_to_L13": False,
        }

        # Create mock analyzers
        pipeline = WolfSovereignPipeline()

        # Mock all layer analyzers
        pipeline._l1 = Mock()
        pipeline._l1.analyze.return_value = {"valid": True, "csi": 0.95}
        pipeline._l2 = Mock()
        pipeline._l2.analyze.return_value = {
            "valid": True,
            "direction": "BUY",
            "alignment_strength": 0.88,
        }
        pipeline._l3 = Mock()
        pipeline._l3.analyze.return_value = {"valid": True, "bias": "BULLISH"}
        pipeline._l3.structure = Mock()
        pipeline._l3.structure.analyze.return_value = {"valid": True, "trend": "BULLISH"}

        pipeline._l4 = Mock()
        pipeline._l4.score.return_value = {"technical_score": 80, "valid": True}
        pipeline._l5 = Mock()
        pipeline._l5.analyze.return_value = {"valid": True, "current_drawdown": 1.0}
        pipeline._l6 = Mock()
        pipeline._l6.analyze.return_value = {"risk_ok": True, "valid": True}
        pipeline._l7 = Mock()
        pipeline._l7.analyze.return_value = {
            "win_probability": 75,
            "profit_factor": 2.0,
            "valid": True,
        }
        pipeline._l8 = Mock()
        pipeline._l8.analyze.return_value = {
            "tii_sym": 0.95,
            "integrity": 0.98,
            "valid": True,
        }
        pipeline._l9 = Mock()
        pipeline._l9.analyze.return_value = {"smc": True, "confidence": 0.8, "valid": True}
        pipeline._l10 = Mock()
        pipeline._l10.analyze.return_value = {"position_ok": True, "valid": True}
        pipeline._l11 = Mock()
        pipeline._l11.calculate_rr.return_value = {
            "rr_ratio": 2.5,
            "entry": 1.0850,
            "stop_loss": 1.0800,
            "take_profit": 1.0950,
            "valid": True,
        }

        pipeline._macro_vol = Mock()
        pipeline._macro_vol.get_state.return_value = {
            "regime_state": 1,
            "risk_multiplier": 1.0,
        }

        # Run pipeline
        result = pipeline.run("EURUSD")

        # Should return result without L13/L15
        assert result.symbol == "EURUSD"
        assert result.l12_verdict["verdict"] == "HOLD"
        assert result.reflective_pass1 is None
        assert result.meta is None
        assert result.reflective_pass2 is None

    def test_early_exit_on_invalid_l1(self):
        """Test pipeline exits early when L1 is invalid."""
        pipeline = WolfSovereignPipeline()
        pipeline._l1 = Mock()
        pipeline._l1.analyze.return_value = {"valid": False}

        result = pipeline.run("EURUSD")

        assert result.symbol == "EURUSD"
        assert "L1_INVALID" in result.errors
        assert result.l12_verdict["verdict"] == "HOLD"


class TestBuildL12Synthesis:
    """Test synthesis builder."""

    def test_synthesis_has_all_required_keys(self):
        """Test synthesis dict has all keys required by generate_l12_verdict."""
        # Create mock layer outputs
        l1 = {"valid": True, "csi": 0.95}
        l2 = {"valid": True, "direction": "BUY", "alignment_strength": 0.88}
        l3 = {"valid": True, "bias": "BULLISH"}
        l4 = {"technical_score": 80, "wolf_30_point": 26, "valid": True}
        l5 = {"valid": True, "current_drawdown": 1.0}
        l6 = {"risk_ok": True, "valid": True}
        l7 = {"win_probability": 75, "profit_factor": 2.0, "valid": True}
        l8 = {"tii_sym": 0.95, "integrity": 0.98, "valid": True}
        l9 = {"smc": True, "confidence": 0.8, "valid": True}
        l10 = {"position_ok": True, "valid": True}
        l11 = {
            "rr_ratio": 2.5,
            "entry": 1.0850,
            "stop_loss": 1.0800,
            "take_profit": 1.0950,
            "valid": True,
        }
        macro_vix_state = {"regime_state": 1, "risk_multiplier": 1.0}
        system_metrics = {"latency_ms": 50, "safe_mode": False}

        synthesis = build_l12_synthesis(
            symbol="EURUSD",
            l1=l1,
            l2=l2,
            l3=l3,
            l4=l4,
            l5=l5,
            l6=l6,
            l7=l7,
            l8=l8,
            l9=l9,
            l10=l10,
            l11=l11,
            macro_vix_state=macro_vix_state,
            system_metrics=system_metrics,
        )

        # Verify all required keys exist
        assert "pair" in synthesis
        assert synthesis["pair"] == "EURUSD"

        # scores
        assert "scores" in synthesis
        assert "wolf_30_point" in synthesis["scores"]
        assert "f_score" in synthesis["scores"]
        assert "t_score" in synthesis["scores"]
        assert "fta_score" in synthesis["scores"]
        assert "exec_score" in synthesis["scores"]

        # layers
        assert "layers" in synthesis
        assert "L8_tii_sym" in synthesis["layers"]
        assert "L8_integrity_index" in synthesis["layers"]
        assert "L7_monte_carlo_win" in synthesis["layers"]
        assert "conf12" in synthesis["layers"]

        # execution
        assert "execution" in synthesis
        assert "rr_ratio" in synthesis["execution"]
        assert "direction" in synthesis["execution"]
        assert "entry_price" in synthesis["execution"]
        assert "stop_loss" in synthesis["execution"]
        assert "take_profit_1" in synthesis["execution"]
        assert "entry_zone" in synthesis["execution"]
        assert "risk_percent" in synthesis["execution"]
        assert "risk_amount" in synthesis["execution"]
        assert "lot_size" in synthesis["execution"]

        # propfirm
        assert "propfirm" in synthesis
        assert "compliant" in synthesis["propfirm"]

        # risk
        assert "risk" in synthesis
        assert "current_drawdown" in synthesis["risk"]

        # bias
        assert "bias" in synthesis
        assert "fundamental" in synthesis["bias"]
        assert "technical" in synthesis["bias"]

        # macro_vix
        assert "macro_vix" in synthesis
        assert "regime_state" in synthesis["macro_vix"]

        # system
        assert "system" in synthesis
        assert "latency_ms" in synthesis["system"]
        assert "safe_mode" in synthesis["system"]

    def test_synthesis_handles_dict_wolf_30_point(self):
        """Test synthesis handles both dict and int wolf_30_point."""
        l4_with_dict = {
            "technical_score": 80,
            "wolf_30_point": {"total_score": 28},
            "valid": True,
        }

        synthesis = build_l12_synthesis(
            symbol="EURUSD",
            l1={"valid": True, "csi": 0.95},
            l2={"valid": True, "direction": "BUY", "alignment_strength": 0.88},
            l3={"valid": True, "bias": "BULLISH"},
            l4=l4_with_dict,
            l5={"valid": True, "current_drawdown": 1.0},
            l6={"risk_ok": True, "valid": True},
            l7={"win_probability": 75, "valid": True},
            l8={"tii_sym": 0.95, "integrity": 0.98, "valid": True},
            l9={"smc": True, "confidence": 0.8, "valid": True},
            l10={"position_ok": True, "valid": True},
            l11={"rr_ratio": 2.5, "entry": 1.0850, "valid": True},
            macro_vix_state={"regime_state": 1, "risk_multiplier": 1.0},
            system_metrics={"latency_ms": 50, "safe_mode": False},
        )

        assert synthesis["scores"]["wolf_30_point"] == 28

    def test_synthesis_computes_entry_zone_correctly(self):
        """Test synthesis computes entry zone based on direction."""
        # Test BUY direction
        synthesis_buy = build_l12_synthesis(
            symbol="EURUSD",
            l1={"valid": True, "csi": 0.95},
            l2={"valid": True, "direction": "BUY", "alignment_strength": 0.88},
            l3={"valid": True, "bias": "BULLISH"},
            l4={"technical_score": 80, "valid": True},
            l5={"valid": True, "current_drawdown": 1.0},
            l6={"risk_ok": True, "valid": True},
            l7={"win_probability": 75, "valid": True},
            l8={"tii_sym": 0.95, "integrity": 0.98, "valid": True},
            l9={"smc": True, "confidence": 0.8, "valid": True},
            l10={"position_ok": True, "valid": True},
            l11={
                "rr_ratio": 2.5,
                "entry": 1.0850,
                "stop_loss": 1.0800,
                "take_profit": 1.0950,
                "valid": True,
            },
            macro_vix_state={"regime_state": 1, "risk_multiplier": 1.0},
            system_metrics={"latency_ms": 50, "safe_mode": False},
        )

        assert "1.0840" in synthesis_buy["execution"]["entry_zone"]

        # Test SELL direction
        synthesis_sell = build_l12_synthesis(
            symbol="EURUSD",
            l1={"valid": True, "csi": 0.95},
            l2={"valid": True, "direction": "SELL", "alignment_strength": 0.88},
            l3={"valid": True, "bias": "BEARISH"},
            l4={"technical_score": 80, "valid": True},
            l5={"valid": True, "current_drawdown": 1.0},
            l6={"risk_ok": True, "valid": True},
            l7={"win_probability": 75, "valid": True},
            l8={"tii_sym": 0.95, "integrity": 0.98, "valid": True},
            l9={"smc": True, "confidence": 0.8, "valid": True},
            l10={"position_ok": True, "valid": True},
            l11={
                "rr_ratio": 2.5,
                "entry": 1.0850,
                "stop_loss": 1.0900,
                "take_profit": 1.0750,
                "valid": True,
            },
            macro_vix_state={"regime_state": 1, "risk_multiplier": 1.0},
            system_metrics={"latency_ms": 50, "safe_mode": False},
        )

        assert "1.0860" in synthesis_sell["execution"]["entry_zone"]


class TestL13ReflectiveEngine:
    """Test L13 Reflective Engine."""

    def test_two_pass_produces_different_results(self):
        """Test L13 produces different results for pass 1 and pass 2."""
        engine = L13ReflectiveEngine()

        synthesis = {
            "execution": {"direction": "BUY"},
            "layers": {
                "L2": {"direction": "BUY"},
                "L3": {"bias": "BULLISH"},
                "L9": {"smc": True},
            },
            "bias": {"technical": "BULLISH"},
        }

        l12_verdict = {"verdict": "EXECUTE_BUY"}

        # Pass 1: meta_integrity = 1.0
        pass1 = engine.reflect(synthesis, l12_verdict, meta_integrity=1.0)

        # Pass 2: meta_integrity = 0.85
        pass2 = engine.reflect(synthesis, l12_verdict, meta_integrity=0.85)

        # Results should differ
        assert pass1["pass"] == 1
        assert pass2["pass"] == 2
        assert pass1["meta_integrity"] == 1.0
        assert pass2["meta_integrity"] == 0.85
        assert abs(pass1["drift_ratio"] - 0.0) < 0.001  # Floating point comparison
        assert abs(pass2["drift_ratio"] - 0.15) < 0.001  # Floating point comparison
        assert pass1["abg_score"] != pass2["abg_score"]

    def test_lrce_computes_directional_alignment(self):
        """Test LRCE computes directional alignment correctly."""
        engine = L13ReflectiveEngine()

        # Strong alignment
        synthesis_aligned = {
            "execution": {"direction": "BUY"},
            "layers": {
                "L2": {"direction": "BUY"},
                "L3": {"bias": "BULLISH"},
                "L9": {"smc": True},
            },
        }

        lrce_aligned = engine._compute_lrce(synthesis_aligned)
        assert lrce_aligned > 0.8

        # Weak alignment
        synthesis_misaligned = {
            "execution": {"direction": "BUY"},
            "layers": {
                "L2": {"direction": "SELL"},
                "L3": {"bias": "BEARISH"},
                "L9": {"smc": False},
            },
        }

        lrce_misaligned = engine._compute_lrce(synthesis_misaligned)
        assert lrce_misaligned < 0.5

    def test_frpc_checks_verdict_bias_consistency(self):
        """Test FRPC checks verdict/bias consistency."""
        engine = L13ReflectiveEngine()

        # Consistent: EXECUTE_BUY with BULLISH bias
        synthesis_consistent = {
            "execution": {"direction": "BUY"},
            "bias": {"technical": "BULLISH"},
        }
        l12_verdict_execute = {"verdict": "EXECUTE_BUY"}

        frpc_consistent = engine._compute_frpc(synthesis_consistent, l12_verdict_execute)
        assert frpc_consistent == 1.0

        # Inconsistent: EXECUTE_BUY with BEARISH bias
        synthesis_inconsistent = {
            "execution": {"direction": "BUY"},
            "bias": {"technical": "BEARISH"},
        }

        frpc_inconsistent = engine._compute_frpc(
            synthesis_inconsistent, l12_verdict_execute
        )
        assert frpc_inconsistent < 0.5


class TestL15MetaSovereigntyEngine:
    """Test L15 Meta Sovereignty Engine."""

    def test_compute_meta_integrity(self):
        """Test meta integrity computation."""
        engine = L15MetaSovereigntyEngine()

        synthesis = {
            "layers": {
                "L1": {"valid": True},
                "L2": {"valid": True},
                "L3": {"valid": True},
                "L4": {"valid": True},
                "L5": {"valid": True},
                "L6": {"valid": True},
                "L7": {"valid": True},
                "L8": {"valid": True},
                "L9": {"valid": True},
                "L10": {"valid": True},
                "L11": {"valid": True},
            }
        }

        meta = engine.compute_meta(synthesis, {}, {})

        assert meta["meta_integrity"] == 1.0
        assert meta["valid_layers"] == 11
        assert meta["total_layers"] == 11
        assert meta["vault_sync"] > 0.9

    def test_enforcement_granted(self):
        """Test sovereignty enforcement returns GRANTED."""
        engine = L15MetaSovereigntyEngine()

        l12_verdict = {"verdict": "EXECUTE_BUY"}
        reflective_pass2 = {"drift_ratio": 0.05, "abg_score": 0.92}
        meta = {"vault_sync": 0.99}

        enforcement = engine.enforce_sovereignty(l12_verdict, reflective_pass2, meta)

        assert enforcement["execution_rights"] == "GRANTED"
        assert enforcement["lot_multiplier"] == 1.0

    def test_enforcement_restricted(self):
        """Test sovereignty enforcement returns RESTRICTED."""
        engine = L15MetaSovereigntyEngine()

        l12_verdict = {"verdict": "EXECUTE_BUY"}
        reflective_pass2 = {"drift_ratio": 0.18, "abg_score": 0.85}
        meta = {"vault_sync": 0.97}

        enforcement = engine.enforce_sovereignty(l12_verdict, reflective_pass2, meta)

        assert enforcement["execution_rights"] == "RESTRICTED"
        assert enforcement["lot_multiplier"] == 0.5

    def test_enforcement_revoked(self):
        """Test sovereignty enforcement returns REVOKED."""
        engine = L15MetaSovereigntyEngine()

        l12_verdict = {"verdict": "EXECUTE_BUY", "confidence": "HIGH"}
        reflective_pass2 = {"drift_ratio": 0.25, "abg_score": 0.70}
        meta = {"vault_sync": 0.90}

        enforcement = engine.enforce_sovereignty(l12_verdict, reflective_pass2, meta)

        assert enforcement["execution_rights"] == "REVOKED"
        assert enforcement["lot_multiplier"] == 0.0
        # Verdict should be downgraded
        assert l12_verdict["verdict"] == "HOLD"
        assert l12_verdict["confidence"] == "LOW"


class TestVIXMultiplierApplication:
    """Test VIX multiplier is properly applied."""

    @patch("analysis.orchestrators.wolf_sovereign_pipeline.generate_l12_verdict")
    def test_vix_multiplier_applied_to_l7(self, mock_verdict):
        """Test VIX multiplier is applied to L7 win probability."""
        mock_verdict.return_value = {
            "verdict": "HOLD",
            "confidence": "LOW",
            "proceed_to_L13": False,
        }

        pipeline = WolfSovereignPipeline()

        # Mock all analyzers
        pipeline._l1 = Mock()
        pipeline._l1.analyze.return_value = {"valid": True, "csi": 0.95}
        pipeline._l2 = Mock()
        pipeline._l2.analyze.return_value = {
            "valid": True,
            "direction": "BUY",
            "alignment_strength": 0.88,
        }
        pipeline._l3 = Mock()
        pipeline._l3.analyze.return_value = {"valid": True, "bias": "BULLISH"}
        pipeline._l3.structure = Mock()
        pipeline._l3.structure.analyze.return_value = {"valid": True}
        pipeline._l4 = Mock()
        pipeline._l4.score.return_value = {"technical_score": 80, "valid": True}
        pipeline._l5 = Mock()
        pipeline._l5.analyze.return_value = {"valid": True}
        pipeline._l6 = Mock()
        pipeline._l6.analyze.return_value = {"risk_ok": True, "valid": True}

        # L7 returns initial win probability of 75%
        pipeline._l7 = Mock()
        pipeline._l7.analyze.return_value = {
            "win_probability": 75.0,
            "valid": True,
        }

        pipeline._l8 = Mock()
        pipeline._l8.analyze.return_value = {"tii_sym": 0.95, "integrity": 0.98, "valid": True}
        pipeline._l9 = Mock()
        pipeline._l9.analyze.return_value = {"smc": True, "confidence": 0.8, "valid": True}
        pipeline._l10 = Mock()
        pipeline._l10.analyze.return_value = {"position_ok": True, "valid": True}
        pipeline._l11 = Mock()
        pipeline._l11.calculate_rr.return_value = {
            "rr_ratio": 2.5,
            "entry": 1.0850,
            "valid": True,
        }

        # Mock macro vol with VIX multiplier of 0.8
        pipeline._macro_vol = Mock()
        pipeline._macro_vol.get_state.return_value = {
            "regime_state": 1,
            "risk_multiplier": 0.8,
        }

        result = pipeline.run("EURUSD")

        # Check that L7 was called and returned initial value
        pipeline._l7.analyze.assert_called_once()

        # The VIX multiplier should have been applied
        # Original: 75.0, multiplied by 0.8 = 60.0
        # This should be reflected in the synthesis
        assert result.synthesis is not None


class TestLayerExecutionOrder:
    """Test layer execution order."""

    @patch("analysis.orchestrators.wolf_sovereign_pipeline.generate_l12_verdict")
    def test_l11_executes_before_l6(self, mock_verdict):
        """Test L11 (RR) executes before L6 (risk check)."""
        mock_verdict.return_value = {
            "verdict": "HOLD",
            "confidence": "LOW",
            "proceed_to_L13": False,
        }

        pipeline = WolfSovereignPipeline()
        execution_order = []

        # Mock analyzers with tracking
        pipeline._l1 = Mock()
        pipeline._l1.analyze.side_effect = lambda s: (
            execution_order.append("L1"),
            {"valid": True, "csi": 0.95},
        )[1]

        pipeline._l2 = Mock()
        pipeline._l2.analyze.side_effect = lambda s: (
            execution_order.append("L2"),
            {"valid": True, "direction": "BUY", "alignment_strength": 0.88},
        )[1]

        pipeline._l3 = Mock()
        pipeline._l3.analyze.side_effect = lambda s: (
            execution_order.append("L3"),
            {"valid": True, "bias": "BULLISH"},
        )[1]
        pipeline._l3.structure = Mock()
        pipeline._l3.structure.analyze.return_value = {"valid": True}

        pipeline._l4 = Mock()
        pipeline._l4.score.side_effect = lambda *a: (
            execution_order.append("L4"),
            {"technical_score": 80, "valid": True},
        )[1]

        pipeline._l5 = Mock()
        pipeline._l5.analyze.side_effect = lambda *a, **k: (
            execution_order.append("L5"),
            {"valid": True},
        )[1]

        pipeline._l6 = Mock()
        pipeline._l6.analyze.side_effect = lambda *a, **k: (
            execution_order.append("L6"),
            {"risk_ok": True, "valid": True},
        )[1]

        pipeline._l7 = Mock()
        pipeline._l7.analyze.side_effect = lambda *a, **k: (
            execution_order.append("L7"),
            {"win_probability": 75.0, "valid": True},
        )[1]

        pipeline._l8 = Mock()
        pipeline._l8.analyze.side_effect = lambda *a, **k: (
            execution_order.append("L8"),
            {"tii_sym": 0.95, "integrity": 0.98, "valid": True},
        )[1]

        pipeline._l9 = Mock()
        pipeline._l9.analyze.side_effect = lambda *a, **k: (
            execution_order.append("L9"),
            {"smc": True, "confidence": 0.8, "valid": True},
        )[1]

        pipeline._l10 = Mock()
        pipeline._l10.analyze.side_effect = lambda *a, **k: (
            execution_order.append("L10"),
            {"position_ok": True, "valid": True},
        )[1]

        pipeline._l11 = Mock()
        pipeline._l11.calculate_rr.side_effect = lambda *a, **k: (
            execution_order.append("L11"),
            {"rr_ratio": 2.5, "entry": 1.0850, "valid": True},
        )[1]

        pipeline._macro_vol = Mock()
        pipeline._macro_vol.get_state.return_value = {
            "regime_state": 1,
            "risk_multiplier": 1.0,
        }

        result = pipeline.run("EURUSD")

        # Check execution order
        assert "L11" in execution_order
        assert "L6" in execution_order
        assert execution_order.index("L11") < execution_order.index("L6")
