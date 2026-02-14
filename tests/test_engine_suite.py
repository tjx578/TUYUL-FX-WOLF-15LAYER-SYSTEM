from engines import create_engine_suite


def test_engine_suite_smoke() -> None:
    suite = create_engine_suite()

    coherence = suite["coherence"].evaluate(
        {
            "emotion_now": 0.6,
            "focus_index": 0.7,
            "reaction_delay_ms": 150,
            "consecutive_losses": 1,
            "session_duration_min": 90,
            "ohlcv_volatility": 0.4,
        }
    )

    closes = [1.0 + i * 0.002 for i in range(80)]
    highs = [c * 1.002 for c in closes]
    lows = [c * 0.998 for c in closes]
    volumes = [1000 + i * 3 for i in range(80)]

    context = suite["context"].analyze(
        {"close": closes, "high": highs, "low": lows, "volume": volumes}
    )
    risk = suite["risk"].simulate([0.001, -0.0005, 0.002, -0.001] * 40)
    field = suite["field"].evaluate(closes, volumes)
    momentum = suite["momentum"].evaluate(
        {"prices": closes, "volumes": volumes, "field_bias": field.field_bias, "trq_energy": 0.4}
    )
    precision = suite["precision"].evaluate(
        {
            "ema8": closes[-1],
            "ema21": closes[-5],
            "ema55": closes[-20],
            "ema100": closes[-40],
            "rsi": 62,
            "macd": 0.004,
            "atr": 0.01,
            "vwap_gap": 0.001,
            "zone_distance": 0.004,
            "volatility": 0.45,
        }
    )
    structure = suite["structure"].evaluate(
        {"close": closes, "high": highs, "low": lows, "volume": volumes, "rsi": [55] * 80}
    )
    probability = suite["probability"].evaluate(
        {
            "context": context.confidence,
            "coherence": coherence.psych_confidence,
            "risk": risk.robustness,
            "momentum": momentum.momentum_strength,
            "precision": precision.precision_weight,
            "structure": structure.mtf_alignment,
            "field": abs(field.field_bias),
        }
    )

    advisory = suite["advisory"].summarize(
        field=field.__dict__,
        probability=probability.__dict__,
        coherence=suite["coherence"].export(coherence),
        context=context.__dict__,
        momentum=momentum.__dict__,
        precision=precision.__dict__,
        structure=structure.__dict__,
        risk=risk.__dict__,
    )

    assert 0.0 <= probability.weighted_probability <= 1.0
    assert advisory.signal in {"STRONG", "MODERATE", "WEAK", "INSUFFICIENT"}
