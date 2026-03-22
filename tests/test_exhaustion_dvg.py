from analysis.exhaustion_dvg_fusion_engine import ExhaustionDivergenceFusionEngine


def test_insufficient_data():
    engine = ExhaustionDivergenceFusionEngine()
    result = engine.analyze(
        osc={"M5": [1.0]},  # Only 1 data point
        price={"M5": [100.0]},
        mode="bullish",
    )
    assert result["confidence"] == 0.0
    assert "INSUFFICIENT_DATA" in result["reason"]


def test_missing_timeframe():
    engine = ExhaustionDivergenceFusionEngine()
    result = engine.analyze(
        osc={"M5": [1.0, 2.0]},  # H4 missing
        price={"M5": [100.0, 99.0]},
        mode="bullish",
    )
    assert result["confidence"] == 0.0
    assert "H4" in result["missing_tfs"]


def test_bullish_divergence_detected():
    engine = ExhaustionDivergenceFusionEngine()
    result = engine.analyze(
        osc={
            "M5": [30.0, 35.0],  # Higher low in RSI
            "M15": [28.0, 33.0],
            "H1": [25.0, 32.0],
            "H4": [20.0, 30.0],
        },
        price={
            "M5": [100.0, 98.0],  # Lower low in price
            "M15": [100.0, 97.0],
            "H1": [100.0, 96.0],
            "H4": [100.0, 95.0],
        },
        mode="bullish",
    )
    assert result["confidence"] == 1.0  # All 4 TFs agree
    assert result["score"] > 0.8
    assert "STRONG_DIVERGENCE" in result["reason"]
