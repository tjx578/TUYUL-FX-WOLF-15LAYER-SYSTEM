from engines import create_engine_suite


def _series(n=160, start=100.0, step=0.08):
    closes, highs, lows, volumes = [], [], [], []
    for i in range(n):
        price = start + i * step + (0.2 if i % 7 == 0 else -0.05)
        closes.append(price)
        highs.append(price + 0.4)
        lows.append(price - 0.4)
        volumes.append(1000 + (i % 9) * 80)
    return closes, highs, lows, volumes


def test_engine_suite_runs_end_to_end():
    suite = create_engine_suite()
    closes, highs, lows, volumes = _series()
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    context = suite["context"].analyze(
        {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}
    )
    coherence = suite["coherence"].evaluate(
        {"emotion_state": 0.15, "fatigue": 0.2, "loss_stress": 0.1}, market_volatility=0.01
    )
    risk = suite["risk"].simulate(returns)
    field = suite["field"].evaluate(closes, volumes)
    momentum = suite["momentum"].evaluate(closes, volumes, trq_energy=0.4)
    precision = suite["precision"].evaluate(
        closes=closes,
        rsi=56,
        macd_hist=0.4,
        atr_pct=0.008,
        support=min(closes[-40:]),
        resistance=max(closes[-40:]),
    )
    structure = suite["structure"].evaluate(highs, lows, closes, volumes, [55.0] * len(closes))

    prob = suite["probability"].evaluate(
        {
            "context": context.regime_confidence,
            "coherence": coherence.coherence_index,
            "risk": risk.robustness,
            "momentum": momentum.momentum_strength,
            "precision": precision.precision_weight,
            "structure": structure.mtf_alignment,
            "field": abs(field.field_bias),
        }
    )

    advisory = suite["advisory"].summarize(
        field=suite["field"].export(field),
        probability=suite["probability"].export(prob),
        coherence=suite["coherence"].export(coherence),
        context=suite["context"].export(context),
        momentum=suite["momentum"].export(momentum),
        precision=suite["precision"].export(precision),
        structure=suite["structure"].export(structure),
        risk=suite["risk"].export(risk),
    )

    assert 0.0 <= prob.weighted_probability <= 1.0
    assert advisory.signal in {"STRONG", "MODERATE", "CAUTIOUS", "WEAK", "INSUFFICIENT"}


def test_advisory_detects_lockout_conflict():
    suite = create_engine_suite()
    advisory = suite["advisory"].summarize(
        field={"field_bias": 0.2, "stability_index": 0.8},
        probability={"weighted_probability": 0.8},
        coherence={"coherence_index": 0.4, "gate": "LOCKOUT"},
        context={"market_regime": "RISK_ON"},
        momentum={"directional_bias": 0.2},
        precision={"precision_weight": 0.8},
        structure={"structure": "BREAKING_OUT", "bearish_divergence": False},
        risk={"robustness": 0.8, "cvar_95": -0.03},
    )
    assert "HIGH_PROB_BUT_LOCKOUT" in advisory.conflicts
