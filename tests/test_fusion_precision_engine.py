from engines import FusionPrecisionEngine


def test_precision_calculation_with_stack_and_confluence():
    engine = FusionPrecisionEngine()
    closes = [100 + i * 0.5 for i in range(130)]
    result = engine.calculate(
        {
            "ema_ratio": 1.02,
            "vwap_deviation": 0.2,
            "atr_norm": 1.1,
            "closes": closes,
            "support_level": closes[-1] * 0.995,
            "resistance_level": closes[-1] * 1.01,
            "rsi": 60,
            "macd_signal": 0.3,
        }
    )

    assert 0.0 <= result.precision_weight <= 1.0
    assert -1.0 <= result.ema_alignment <= 1.0
    assert result.confluence_score >= 0.0
    assert result.zone_proximity >= 0.0


def test_high_volatility_penalty_applied():
    engine = FusionPrecisionEngine()
    indicators = {
        "ema_ratio": 0.8,
        "vwap_deviation": 0.1,
        "atr_norm": 3.0,
        "rsi": 50,
        "macd_signal": -0.2,
    }

    result = engine.calculate(indicators)
    assert 0.0 <= result.precision_weight <= 1.0
    assert result.volatility_adjustment == 3.0


def test_export_schema_keys():
    engine = FusionPrecisionEngine()
    result = engine.calculate({"ema_ratio": 1.0, "vwap_deviation": 0.0, "atr_norm": 1.0})

    payload = engine.export(result)
    assert set(payload.keys()) == {
        "precision_weight",
        "ema_alignment",
        "vwap_deviation",
        "volatility_adjustment",
        "confluence_score",
        "zone_proximity",
        "details",
    }
