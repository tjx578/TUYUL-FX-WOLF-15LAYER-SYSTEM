from engines import create_engine_suite


def test_create_engine_suite_has_all_engines():
    suite = create_engine_suite()
    assert {
        "coherence",
        "context",
        "risk",
        "momentum",
        "precision",
        "structure",
        "field",
        "probability",
        "advisory",
    }.issubset(suite.keys())


def test_advisory_flags_lockout_conflict():
    suite = create_engine_suite()
    advisory = suite["advisory"]
    summary = advisory.summarize(  # type: ignore[attr-defined]
        field={"valid": True, "field_energy": 0.1, "field_bias": 0.3, "stability_index": 0.6},
        probability={"valid": True, "weighted_probability": 0.75, "uncertainty": 0.2},
        coherence={"gate": "LOCKOUT", "coherence_index": 0.5, "psych_confidence": 0.4},
    )
    assert "HIGH_PROB_BUT_LOCKOUT" in summary.conflict_flags
    assert summary.valid is True
import math

from engines import create_engine_suite


def _series(n=160, start=100.0, step=0.08):
    """
    Generate a deterministic but more realistic synthetic market series with:
    - Multiple regimes (range → trend → choppy)
    - Non-monotonic price paths
    - Some volatility clustering
    - Non-trivial, deterministic 'noise' via trigonometric functions
    """
    closes, highs, lows, volumes = [], [], [], []

    # Split into three regimes
    regime_1_end = n // 3  # mean-reverting / range
    regime_2_end = 2 * n // 3  # trending with higher volatility
    # regime 3: choppy / volatile (rest)

    last_price = start
    for i in range(n):
        if i < regime_1_end:
            # Range / mean-reverting around `start`
            # Small oscillations, slight mean reversion
            drift = 0.0
            noise = 0.4 * math.sin(i / 3.0) + 0.2 * math.cos(i / 5.0)
        elif i < regime_2_end:
            # Upward trend with higher volatility and some autocorrelation
            drift = step * 1.5
            noise = 0.6 * math.sin(i / 4.0) + 0.3 * math.cos(i / 6.0)
        else:
            # Choppy / volatile regime
            drift = -step * 0.5
            noise = 0.8 * math.sin(i / 2.0) + 0.5 * math.cos(i / 3.0)

        price = last_price + drift + noise
        closes.append(price)

        # Add realistic high/low spread with some volatility
        spread = abs(noise) * 0.5 + 0.3
        highs.append(price + spread)
        lows.append(price - spread)

        # Volume with regime-dependent patterns
        base_vol = 1000
        if i < regime_1_end:
            vol_mult = 1.0 + 0.2 * math.sin(i / 5.0)
        elif i < regime_2_end:
            vol_mult = 1.3 + 0.3 * math.sin(i / 4.0)  # Higher volume in trend
        else:
            vol_mult = 1.5 + 0.5 * math.sin(i / 2.0)  # Highest in volatile regime
        volumes.append(base_vol * vol_mult)

        last_price = price

    return closes, highs, lows, volumes


def _series_simple(n=160, start=100.0, step=0.08):
    """Simple monotonic series for basic smoke tests."""
    closes, highs, lows, volumes = [], [], [], []
    for i in range(n):
        price = start + i * step + (0.2 if i % 7 == 0 else -0.05)
        closes.append(price)
        highs.append(price + 0.4)
        lows.append(price - 0.4)
        volumes.append(1000 + (i % 9) * 80)
    return closes, highs, lows, volumes


def test_engine_suite_runs_end_to_end():
    """Test end-to-end engine orchestration with realistic multi-regime data."""
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


def test_engine_suite_simple():
    """Test basic smoke test with simple monotonic data."""
    suite = create_engine_suite()
    closes, highs, lows, volumes = _series_simple()
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    context = suite["context"].analyze(
        {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}
    )
    coherence = suite["coherence"].evaluate(
        {"emotion_state": 0.15, "fatigue": 0.2, "loss_stress": 0.1}, market_volatility=0.01
    )
    risk = suite["risk"].simulate(returns)

    assert context.market_regime in {"RISK_ON", "RISK_OFF", "TRANSITIONAL"}
    assert 0.0 <= coherence.coherence_index <= 1.0
    assert -1.0 <= risk.cvar_95 <= 1.0


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
