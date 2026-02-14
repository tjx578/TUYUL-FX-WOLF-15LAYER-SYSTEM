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
from engines import (
    AdvisorySignal,
    CognitiveCoherence,
    CognitiveContext,
    CognitiveRiskSimulation,
    FusionMomentum,
    FusionPrecision,
    FusionStructure,
    ProbabilityResult,
    create_engine_suite,
)


def test_create_engine_suite_has_all_expected_engines() -> None:
    suite = create_engine_suite()
    assert set(suite.keys()) == {
        "coherence",
        "context",
        "risk_sim",
        "momentum",
        "precision",
        "structure",
        "field",
        "probability",
        "advisory",
    }


def test_engines_evaluate_expected_contract_shapes() -> None:
    suite = create_engine_suite()
    state = {
        "emotion_balance": 0.7,
        "reflex_pressure": 0.2,
        "integrity_score": 0.8,
        "trend_strength": 0.7,
        "volatility": 0.3,
        "structure_bias": 0.4,
        "liquidity_depth": 0.8,
        "institutional_flow": 0.75,
        "effective_leverage": 1.2,
        "gap_risk": 0.2,
        "momentum_velocity": 0.4,
        "momentum_impulse": 0.3,
        "precision_weights": [0.6, 0.8, 0.7],
        "ema_fast": 0.6,
        "ema_slow": 0.55,
        "divergence_score": 0.2,
        "liquidity_signal": 0.7,
        "mtf_alignment": 0.8,
        "directional_pressure": 0.35,
        "signal_coherence": 0.8,
        "market_noise": 0.2,
    }

    coherence = suite["coherence"].evaluate(state)
    context = suite["context"].evaluate(state)
    risk = suite["risk_sim"].evaluate(state)
    momentum = suite["momentum"].evaluate(state)
    precision = suite["precision"].evaluate(state)
    structure = suite["structure"].evaluate(state)
    field = suite["field"].evaluate(state)
    probability = suite["probability"].evaluate(
        {
            "coherence": coherence.score,
            "context": 0.7,
            "momentum": momentum.trq_energy,
            "precision": precision.precision_weight,
            "structure": 0.75,
        }
    )
    advisory = suite["advisory"].evaluate(
        {
            "probability": probability.probability,
            "bias": field.bias,
            "tail_risk": risk.tail_risk_score,
        }
    )

    assert isinstance(coherence, CognitiveCoherence)
    assert isinstance(context, CognitiveContext)
    assert isinstance(momentum, FusionMomentum)
    assert isinstance(precision, FusionPrecision)
    assert isinstance(structure, FusionStructure)
    assert isinstance(probability, ProbabilityResult)
    assert advisory.signal in (AdvisorySignal.BUY, AdvisorySignal.SELL, AdvisorySignal.HOLD)


def test_risk_simulation_conservative_pass_fail_boundary() -> None:
    simulator = CognitiveRiskSimulation()
    safe = simulator.evaluate({"effective_leverage": 1.0, "volatility": 0.2, "gap_risk": 0.1})
    unsafe = simulator.evaluate({"effective_leverage": 3.0, "volatility": 1.0, "gap_risk": 1.0})
    assert safe.pass_gate is True
    assert unsafe.pass_gate is False
