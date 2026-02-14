"""
Unit tests for VIX Analysis Engine.

Tests VIX regime classification, fear/greed scoring, and term structure detection.
"""

from analysis.vix_analysis_engine import VIXAnalysisEngine, VIXState


class TestVIXAnalysisEngine:
    """Test VIX analysis functionality."""

    def test_vix_regime_low(self) -> None:
        """Test LOW regime classification (VIX < 14)."""
        engine = VIXAnalysisEngine()
        result = engine.analyze(12.0)
        
        assert isinstance(result, VIXState)
        assert result.vix_regime == "LOW"
        assert result.vix_level == 12.0
        assert 0 <= result.fear_greed_score <= 1
        assert 0 <= result.regime_score <= 1

    def test_vix_regime_elevated(self) -> None:
        """Test ELEVATED regime classification (14-20)."""
        engine = VIXAnalysisEngine()
        result = engine.analyze(17.0)
        
        assert result.vix_regime == "ELEVATED"
        assert result.vix_level == 17.0

    def test_vix_regime_high(self) -> None:
        """Test HIGH regime classification (VIX >= 20)."""
        engine = VIXAnalysisEngine()
        result = engine.analyze(25.0)
        
        assert result.vix_regime == "HIGH"
        assert result.vix_level == 25.0

    def test_fear_greed_score_boundaries(self) -> None:
        """Test fear/greed score at boundaries."""
        engine = VIXAnalysisEngine()
        
        # Low VIX = low fear
        result_low = engine.analyze(8.0)
        assert result_low.fear_greed_score == 0.0
        
        # High VIX = high fear
        result_high = engine.analyze(60.0)
        assert result_high.fear_greed_score == 1.0

    def test_regime_score_boundaries(self) -> None:
        """Test regime score at boundaries."""
        engine = VIXAnalysisEngine()
        
        # Low VIX = low danger
        result_low = engine.analyze(10.0)
        assert result_low.regime_score == 0.1
        
        # High VIX = high danger
        result_high = engine.analyze(50.0)
        assert result_high.regime_score == 1.0

    def test_vix_input_validation(self) -> None:
        """Test VIX input is clamped to valid range."""
        engine = VIXAnalysisEngine()
        
        # Negative should be clamped to 0
        result_neg = engine.analyze(-5.0)
        assert result_neg.vix_level >= 0
        
        # Over 100 should be clamped
        result_high = engine.analyze(150.0)
        assert result_high.vix_level <= 100

    def test_term_structure_unknown_with_little_history(self) -> None:
        """Test term structure is UNKNOWN with insufficient history."""
        engine = VIXAnalysisEngine()
        
        # First analysis should have UNKNOWN term structure
        result = engine.analyze(15.0)
        assert result.term_structure == "UNKNOWN"

    def test_term_structure_detection(self) -> None:
        """Test term structure detection with sufficient history."""
        engine = VIXAnalysisEngine()
        
        # Build history with declining VIX (CONTANGO)
        for vix in [20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10]:
            engine.analyze(vix)
        
        result = engine.analyze(10.0)
        assert result.term_structure in ["CONTANGO", "FLAT", "BACKWARDATION"]

    def test_history_length_limit(self) -> None:
        """Test that history is limited to max_history."""
        engine = VIXAnalysisEngine(history_length=10)
        
        # Add more than 10 VIX values
        for i in range(20):
            engine.analyze(15.0 + i * 0.1)
        
        # History should be capped at 10
        assert len(engine._vix_history) == 10
