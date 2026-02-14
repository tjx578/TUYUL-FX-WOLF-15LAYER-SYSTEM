from engines import create_engine_suite


def test_engine_suite_smoke_flow():
    suite = create_engine_suite()

    prices = [1.10 + i * 0.0008 for i in range(150)]
    highs = [p + 0.0009 for p in prices]
    lows = [p - 0.0008 for p in prices]
    volumes = [1000 + (i % 10) * 40 for i in range(150)]
    returns = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]

    context = suite["context"].analyze(
        {"open": prices, "high": highs, "low": lows, "close": prices, "volume": volumes}
    )

    coherence = None
    for _ in range(8):
        coherence = suite["coherence"].evaluate(
            {
                "emotion_level": 0.98,
                "loss_stress": 1.0,
                "fatigue": 0.95,
                "market_volatility": 0.95,
            }
        )

    risk = suite["risk"].simulate(returns)
    momentum = suite["momentum"].evaluate(
        {"price": prices, "volume": volumes, "trq_energy": 0.5, "field_bias": 0.4}
    )
    precision = suite["precision"].evaluate(
        {
            "price": prices,
            "rsi": 61,
            "macd": 0.004,
            "atr": 0.001,
            "support": prices[-1] - 0.002,
            "resistance": prices[-1] + 0.003,
            "volatility": 0.6,
        }
    )
    structure = suite["structure"].evaluate(
        {
            "close": prices,
            "high": highs,
            "low": lows,
            "volume": volumes,
            "rsi_series": [50 + (i % 12) for i in range(150)],
        }
    )
    field = suite["field"].evaluate(prices, volumes)
    probability = suite["probability"].compute(
        {"L0_regime": 0.7, "L2_fusion": 0.82, "L7_structural": 0.78, "L12_verdict": 0.75}
    )
    advisory = suite["advisory"].summarize(
        field=field,
        probability=probability,
        coherence=coherence,
        context=context,
        momentum=momentum,
        precision=precision,
        structure=structure,
        risk=risk,
    )

    assert context.valid
    assert risk.valid
    assert momentum.valid
    assert precision.valid
    assert structure.valid
    assert field.valid
    assert probability.valid
    assert advisory.valid
    assert "HIGH_PROB_BUT_LOCKOUT" in advisory.conflicts
