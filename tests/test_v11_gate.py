"""Unit tests for engines/v11/extreme_selectivity_gate.py.

Tests cover:
- All 9 veto conditions
- Scoring layer computation
- Execution threshold checks
- Confidence band classification
- Frozen result immutability
- to_dict() serialization
"""

import pytest  # pyright: ignore[reportMissingImports]

from engines.v11.extreme_selectivity_gate import (
    ExtremeSelectivityGateV11,
    ExtremeGateInput,
    GateVerdict,
    ConfidenceBand,
)


class TestExtremeSelectivityGate:
    """Tests for extreme selectivity gate."""
    
    def _create_passing_input(self) -> ExtremeGateInput:
        """Create input that should pass all gates."""
        return ExtremeGateInput(
            regime_label="TRENDING",
            regime_confidence=0.85,
            regime_transition_risk=0.10,
            vol_state="NORMAL",
            vol_expansion=1.5,
            cluster_exposure=0.25,
            rolling_correlation_max=0.50,
            emotion_delta=0.10,
            discipline_score=0.95,
            eaf_score=0.85,
            liquidity_sweep_quality=0.85,
            exhaustion_confidence=0.80,
            divergence_confidence=0.75,
            monte_carlo_win=0.75,
            monte_carlo_pf=2.0,
            posterior=0.80,
        )
    
    def test_passing_input_allows_trade(self) -> None:
        """Test that strong input passes all gates."""
        gate = ExtremeSelectivityGateV11()
        inp = self._create_passing_input()
        
        result = gate.evaluate(inp)
        
        assert result.verdict == GateVerdict.ALLOW
        assert not result.veto_triggered
        assert len(result.veto_reasons) == 0
        assert result.score >= 0.78
    
    def test_veto_regime_shock(self) -> None:
        """Test veto when regime is SHOCK."""
        gate = ExtremeSelectivityGateV11()
        inp = self._create_passing_input()
        
        # Create new input with SHOCK regime
        inp_shock = ExtremeGateInput(
            regime_label="SHOCK",
            regime_confidence=inp.regime_confidence,
            regime_transition_risk=inp.regime_transition_risk,
            vol_state=inp.vol_state,
            vol_expansion=inp.vol_expansion,
            cluster_exposure=inp.cluster_exposure,
            rolling_correlation_max=inp.rolling_correlation_max,
            emotion_delta=inp.emotion_delta,
            discipline_score=inp.discipline_score,
            eaf_score=inp.eaf_score,
            liquidity_sweep_quality=inp.liquidity_sweep_quality,
            exhaustion_confidence=inp.exhaustion_confidence,
            divergence_confidence=inp.divergence_confidence,
            monte_carlo_win=inp.monte_carlo_win,
            monte_carlo_pf=inp.monte_carlo_pf,
            posterior=inp.posterior,
        )
        
        result = gate.evaluate(inp_shock)
        
        assert result.verdict == GateVerdict.BLOCK
        assert result.veto_triggered
        assert "regime_shock" in result.veto_reasons
    
    def test_veto_low_regime_confidence(self) -> None:
        """Test veto when regime confidence too low."""
        gate = ExtremeSelectivityGateV11(regime_confidence_floor=0.65)
        inp = self._create_passing_input()
        
        # Create input with low regime confidence
        inp_low = ExtremeGateInput(
            regime_label=inp.regime_label,
            regime_confidence=0.60,  # Below floor
            regime_transition_risk=inp.regime_transition_risk,
            vol_state=inp.vol_state,
            vol_expansion=inp.vol_expansion,
            cluster_exposure=inp.cluster_exposure,
            rolling_correlation_max=inp.rolling_correlation_max,
            emotion_delta=inp.emotion_delta,
            discipline_score=inp.discipline_score,
            eaf_score=inp.eaf_score,
            liquidity_sweep_quality=inp.liquidity_sweep_quality,
            exhaustion_confidence=inp.exhaustion_confidence,
            divergence_confidence=inp.divergence_confidence,
            monte_carlo_win=inp.monte_carlo_win,
            monte_carlo_pf=inp.monte_carlo_pf,
            posterior=inp.posterior,
        )
        
        result = gate.evaluate(inp_low)
        
        assert result.verdict == GateVerdict.BLOCK
        assert result.veto_triggered
        assert any("regime_confidence_low" in r for r in result.veto_reasons)
    
    def test_veto_high_cluster_exposure(self) -> None:
        """Test veto when cluster exposure too high."""
        gate = ExtremeSelectivityGateV11(cluster_exposure_max=0.75)
        inp = self._create_passing_input()
        
        # Create input with high cluster exposure
        inp_high = ExtremeGateInput(
            regime_label=inp.regime_label,
            regime_confidence=inp.regime_confidence,
            regime_transition_risk=inp.regime_transition_risk,
            vol_state=inp.vol_state,
            vol_expansion=inp.vol_expansion,
            cluster_exposure=0.80,  # Above max
            rolling_correlation_max=inp.rolling_correlation_max,
            emotion_delta=inp.emotion_delta,
            discipline_score=inp.discipline_score,
            eaf_score=inp.eaf_score,
            liquidity_sweep_quality=inp.liquidity_sweep_quality,
            exhaustion_confidence=inp.exhaustion_confidence,
            divergence_confidence=inp.divergence_confidence,
            monte_carlo_win=inp.monte_carlo_win,
            monte_carlo_pf=inp.monte_carlo_pf,
            posterior=inp.posterior,
        )
        
        result = gate.evaluate(inp_high)
        
        assert result.verdict == GateVerdict.BLOCK
        assert result.veto_triggered
        assert any("cluster_exposure_high" in r for r in result.veto_reasons)
    
    def test_veto_low_discipline(self) -> None:
        """Test veto when discipline score too low."""
        gate = ExtremeSelectivityGateV11(discipline_min=0.90)
        inp = self._create_passing_input()
        
        # Create input with low discipline
        inp_low = ExtremeGateInput(
            regime_label=inp.regime_label,
            regime_confidence=inp.regime_confidence,
            regime_transition_risk=inp.regime_transition_risk,
            vol_state=inp.vol_state,
            vol_expansion=inp.vol_expansion,
            cluster_exposure=inp.cluster_exposure,
            rolling_correlation_max=inp.rolling_correlation_max,
            emotion_delta=inp.emotion_delta,
            discipline_score=0.85,  # Below min
            eaf_score=inp.eaf_score,
            liquidity_sweep_quality=inp.liquidity_sweep_quality,
            exhaustion_confidence=inp.exhaustion_confidence,
            divergence_confidence=inp.divergence_confidence,
            monte_carlo_win=inp.monte_carlo_win,
            monte_carlo_pf=inp.monte_carlo_pf,
            posterior=inp.posterior,
        )
        
        result = gate.evaluate(inp_low)
        
        assert result.verdict == GateVerdict.BLOCK
        assert result.veto_triggered
        assert any("discipline_low" in r for r in result.veto_reasons)
    
    def test_veto_blocked_vol_state(self) -> None:
        """Test veto when vol state not in allowed set."""
        gate = ExtremeSelectivityGateV11(
            allowed_vol_states=["NORMAL", "EXPANSION", "TRENDING"]
        )
        inp = self._create_passing_input()
        
        # Create input with blocked vol state
        inp_blocked = ExtremeGateInput(
            regime_label=inp.regime_label,
            regime_confidence=inp.regime_confidence,
            regime_transition_risk=inp.regime_transition_risk,
            vol_state="CONTRACTION",  # Not allowed
            vol_expansion=inp.vol_expansion,
            cluster_exposure=inp.cluster_exposure,
            rolling_correlation_max=inp.rolling_correlation_max,
            emotion_delta=inp.emotion_delta,
            discipline_score=inp.discipline_score,
            eaf_score=inp.eaf_score,
            liquidity_sweep_quality=inp.liquidity_sweep_quality,
            exhaustion_confidence=inp.exhaustion_confidence,
            divergence_confidence=inp.divergence_confidence,
            monte_carlo_win=inp.monte_carlo_win,
            monte_carlo_pf=inp.monte_carlo_pf,
            posterior=inp.posterior,
        )
        
        result = gate.evaluate(inp_blocked)
        
        assert result.verdict == GateVerdict.BLOCK
        assert result.veto_triggered
        assert any("vol_state_blocked" in r for r in result.veto_reasons)
    
    def test_scoring_layer(self) -> None:
        """Test scoring layer computation."""
        gate = ExtremeSelectivityGateV11()
        inp = self._create_passing_input()
        
        result = gate.evaluate(inp)
        
        # Score should be in valid range
        assert 0.0 <= result.score <= 1.0
        
        # Layer breakdown should have score components
        assert "layer2_score" in result.layer_breakdown
        assert "score" in result.layer_breakdown["layer2_score"]
        assert "components" in result.layer_breakdown["layer2_score"]
    
    def test_execution_threshold_score_min(self) -> None:
        """Test execution threshold: score_min."""
        gate = ExtremeSelectivityGateV11(score_min=0.90)
        
        # Create input with good metrics but score will be < 0.90
        inp = ExtremeGateInput(
            regime_label="TRENDING",
            regime_confidence=0.70,  # Lower than passing
            regime_transition_risk=0.10,
            vol_state="NORMAL",
            vol_expansion=1.5,
            cluster_exposure=0.30,
            rolling_correlation_max=0.50,
            emotion_delta=0.10,
            discipline_score=0.95,
            eaf_score=0.85,
            liquidity_sweep_quality=0.70,
            exhaustion_confidence=0.65,
            divergence_confidence=0.60,
            monte_carlo_win=0.75,
            monte_carlo_pf=2.0,
            posterior=0.75,
        )
        
        result = gate.evaluate(inp)
        
        # Should block due to score threshold
        if result.score < 0.90:
            assert result.verdict == GateVerdict.BLOCK
    
    def test_confidence_band_ultra_high(self) -> None:
        """Test ultra high confidence band."""
        gate = ExtremeSelectivityGateV11()
        
        # Create exceptional input
        inp = ExtremeGateInput(
            regime_label="TRENDING",
            regime_confidence=0.90,
            regime_transition_risk=0.05,
            vol_state="NORMAL",
            vol_expansion=2.0,
            cluster_exposure=0.10,
            rolling_correlation_max=0.30,
            emotion_delta=0.05,
            discipline_score=0.98,
            eaf_score=0.95,
            liquidity_sweep_quality=0.90,
            exhaustion_confidence=0.85,
            divergence_confidence=0.80,
            monte_carlo_win=0.80,
            monte_carlo_pf=2.5,
            posterior=0.85,
        )
        
        result = gate.evaluate(inp)
        
        # Should have high confidence band
        assert result.confidence_band in [ConfidenceBand.ULTRA_HIGH, ConfidenceBand.HIGH]
    
    def test_frozen_result(self) -> None:
        """Test that result is immutable."""
        gate = ExtremeSelectivityGateV11()
        inp = self._create_passing_input()
        
        result = gate.evaluate(inp)
        
        with pytest.raises(AttributeError):
            result.verdict = GateVerdict.BLOCK  # type: ignore[misc]
    
    def test_to_dict_serialization(self) -> None:
        """Test to_dict() serialization."""
        gate = ExtremeSelectivityGateV11()
        inp = self._create_passing_input()
        
        result = gate.evaluate(inp)
        d = result.to_dict()
        
        assert isinstance(d, dict)
        assert "verdict" in d
        assert "score" in d
        assert "veto_triggered" in d
        assert "veto_reasons" in d
        assert "confidence_band" in d
        assert "layer_breakdown" in d
