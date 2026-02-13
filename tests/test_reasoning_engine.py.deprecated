"""
Tests for Wolf 15-Layer Reasoning Engine

Validates the integration of the reasoning engine with real analyzers.
"""

import pytest

from reasoning import Wolf15LayerEngine, Wolf15LayerTemplatePopulator


class TestWolf15LayerEngine:
    """Test the Wolf15LayerEngine with real analyzer integration"""

    def test_engine_initialization(self):
        """Test that engine initializes correctly with all analyzers"""
        engine = Wolf15LayerEngine()
        
        assert engine.l1 is not None
        assert engine.l2 is not None
        assert engine.l3 is not None
        assert engine.l4 is not None
        assert engine.l5 is not None
        assert engine.l6 is not None
        assert engine.l7 is not None
        assert engine.l8 is not None
        assert engine.l9 is not None
        assert engine.l10 is not None
        assert engine.l11 is not None

    def test_engine_reset(self):
        """Test that engine reset clears context and logs"""
        engine = Wolf15LayerEngine()
        
        # Add some data
        engine.context.pair = "EURUSD"
        engine.layer_results.append("test")
        engine.execution_log.append("test log")
        
        # Reset
        engine.reset()
        
        assert engine.context.pair == ""
        assert len(engine.layer_results) == 0
        assert len(engine.execution_log) == 0

    def test_engine_log(self):
        """Test that logging works correctly"""
        engine = Wolf15LayerEngine()
        
        engine.log("Test message")
        
        assert len(engine.execution_log) == 1
        assert engine.execution_log[0] == "Test message"

    def test_execute_from_precomputed(self):
        """Test execute_from_precomputed mode for backward compatibility"""
        engine = Wolf15LayerEngine()
        
        # Sample precomputed data
        analysis_data = {
            "pair": "EURUSD",
            "timestamp": "2025-02-06 15:30 GMT+8",
            "current_price": 1.0850,
            "technical_bias": "BULLISH",
        }
        
        result = engine.execute_from_precomputed(analysis_data)
        
        # Should return output dictionary
        assert isinstance(result, dict)
        assert result["pair"] == "EURUSD"
        assert "verdict" in result
        assert "confidence" in result
        assert "scores" in result
        assert "execution" in result

    def test_generate_output_structure(self):
        """Test that _generate_output produces correct structure"""
        engine = Wolf15LayerEngine()
        engine.context.pair = "EURUSD"
        engine.context.wolf_30_score = 25
        
        output = engine._generate_output()
        
        # Check required fields
        assert "pair" in output
        assert "verdict" in output
        assert "confidence" in output
        assert "wolf_status" in output
        assert "scores" in output
        assert "gates" in output
        assert "execution" in output
        assert "layer_outputs" in output
        assert "layer_states" in output
        assert "layer_results" in output
        assert "execution_log" in output
        
        # Check scores structure
        assert "wolf_30" in output["scores"]
        assert "f_score" in output["scores"]
        assert "t_score" in output["scores"]
        assert "fta_score" in output["scores"]
        assert "fta_score_int" in output["scores"]
        assert "psychology" in output["scores"]
        
        # Check gates structure
        assert "passed" in output["gates"]
        assert "total" in output["gates"]
        
        # Check execution structure
        assert "entry" in output["execution"]
        assert "stop_loss" in output["execution"]
        assert "take_profit_1" in output["execution"]
        assert "rr_ratio" in output["execution"]
        assert "execution_mode" in output["execution"]


class TestWolf15LayerTemplatePopulator:
    """Test the template populator"""

    def test_template_initialization(self):
        """Test that template populator initializes correctly"""
        sample_data = {
            "pair": "EURUSD",
            "verdict": "EXECUTE_BUY",
            "confidence": "HIGH",
            "wolf_status": "PACK_HUNT",
            "scores": {
                "wolf_30": 27,
                "f_score": 6,
                "t_score": 11,
                "fta_score": 72.5,
            },
            "gates": {
                "passed": 9,
                "total": 9,
            },
            "execution": {
                "entry": 1.0850,
                "stop_loss": 1.0820,
                "take_profit_1": 1.0910,
                "rr_ratio": 2.0,
            },
        }
        
        populator = Wolf15LayerTemplatePopulator(sample_data)
        
        assert populator.data == sample_data

    def test_get_l4_scores_display(self):
        """Test L4 scores display generation"""
        sample_data = {
            "scores": {
                "f_score": 6,
                "t_score": 11,
                "wolf_30": 27,
            },
            "wolf_status": "PACK_HUNT",
        }
        
        populator = Wolf15LayerTemplatePopulator(sample_data)
        display = populator.get_l4_scores()
        
        assert "F-Score: [6/7]" in display
        assert "T-Score: [11/13]" in display
        assert "Wolf 30: [27/30]" in display
        assert "PACK_HUNT" in display

    def test_get_l12_verdict_display(self):
        """Test L12 verdict display generation"""
        sample_data = {
            "verdict": "EXECUTE_BUY",
            "confidence": "HIGH",
            "wolf_status": "PACK_HUNT",
            "gates": {
                "passed": 9,
                "total": 9,
            },
        }
        
        populator = Wolf15LayerTemplatePopulator(sample_data)
        display = populator.get_l12_verdict()
        
        assert "FINAL VERDICT" in display
        assert "EXECUTE_BUY" in display
        assert "HIGH" in display
        assert "PACK_HUNT" in display
        assert "9/9" in display

    def test_get_execution_table_display(self):
        """Test execution table display generation"""
        sample_data = {
            "execution": {
                "entry": 1.0850,
                "stop_loss": 1.0820,
                "take_profit_1": 1.0910,
                "rr_ratio": 2.0,
            },
        }
        
        populator = Wolf15LayerTemplatePopulator(sample_data)
        display = populator.get_execution_table()
        
        assert "Entry" in display
        assert "1.085" in display  # Formatted number
        assert "Stop Loss" in display
        assert "1.082" in display  # Formatted number
        assert "Take Profit 1" in display
        assert "1.091" in display  # Formatted number
        assert "RR Ratio" in display
        assert "1:2.0" in display
        assert "TP1_ONLY" in display

    def test_to_json_export(self):
        """Test JSON export functionality"""
        sample_data = {
            "pair": "EURUSD",
            "verdict": "EXECUTE_BUY",
            "confidence": "HIGH",
        }
        
        populator = Wolf15LayerTemplatePopulator(sample_data)
        json_output = populator.to_json()
        
        assert isinstance(json_output, str)
        assert "EURUSD" in json_output
        assert "EXECUTE_BUY" in json_output
        assert "HIGH" in json_output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
