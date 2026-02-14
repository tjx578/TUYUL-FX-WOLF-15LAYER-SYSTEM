from engines import create_engine_suite


def test_engine_suite_smoke() -> None:
    suite = create_engine_suite()
    context = suite["context"].analyze(
        {
            "closes": [100 + i * 0.2 for i in range(60)],
            "highs": [100 + i * 0.25 for i in range(60)],
            "lows": [100 + i * 0.15 for i in range(60)],
            "volumes": [1000 + (i % 10) * 20 for i in range(60)],
        }
    )
    field = suite["field"].evaluate(
        [100 + i * 0.2 for i in range(60)], [1000 + i for i in range(60)]
    )
    momentum = suite["momentum"].evaluate(
        {
            "trq_energy": 0.9,
            "reflective_intensity": 0.8,
            "field_bias": 0.4,
            "closes": [100 + i * 0.2 for i in range(60)],
            "volumes": [1000 + i for i in range(60)],
        }
    )
    risk = suite["risk"].simulate([0.01, -0.005, 0.002, 0.007, -0.003] * 20)
    coherence = suite["coherence"].evaluate(
        {"emotion_state": 0.45, "fatigue": 0.15, "loss_stress": 0.1}
    )
    precision = suite["precision"].evaluate(
        {
            "ema8": 105,
            "ema21": 104,
            "ema55": 103,
            "ema100": 102,
            "rsi": 56,
            "macd": 0.4,
            "atr": 0.8,
            "vwap_delta": 0.2,
            "sr_distance": 0.7,
            "price": 106,
        }
    )
    structure = suite["structure"].evaluate(
        {
            "closes": [100 + i * 0.2 for i in range(60)],
            "rsi": [45 + i * 0.1 for i in range(60)],
        }
    )
    probability = suite["probability"].evaluate(
        {
            "context": 0.7,
            "coherence": coherence.coherence_index,
            "risk": risk.robustness,
            "momentum": momentum.momentum_strength,
            "precision": precision.precision_weight,
            "structure": 0.65,
            "field": 0.68,
        }
    )
    advisory = suite["advisory"].summarize(
        field=field.__dict__,
        probability=probability.__dict__,
        coherence=coherence.__dict__,
        context=context.__dict__,
        momentum=momentum.__dict__,
        precision=precision.__dict__,
        structure=structure.__dict__,
        risk=risk.__dict__,
    )

    assert 0.0 <= probability.weighted_probability <= 1.0
    assert advisory.signal in {"STRONG", "MODERATE", "WEAK", "INSUFFICIENT"}
