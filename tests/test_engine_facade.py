from __future__ import annotations

from engines import (
    AdvisoryResult,
    CognitiveContext,
    CognitiveRiskSimulation,
    CoherenceSnapshot,
    FieldResult,
    FusionMomentum,
    FusionPrecision,
    FusionStructure,
    ProbabilityResult,
    RiskSimulationResult,
    create_engine_suite,
)


def _build_multi_tf_candles(size: int = 180) -> dict[str, list[dict[str, float]]]:
    closes = [1.10 + i * 0.0003 + ((-1) ** i) * 0.00008 for i in range(size)]
    candles = [
        {
            "open": closes[i - 1] if i > 0 else closes[i],
            "high": closes[i] + 0.0006,
            "low": closes[i] - 0.0006,
            "close": closes[i],
            "volume": 1000 + (i % 15) * 20,
        }
        for i in range(size)
    ]
    return {
        "M15": candles,
        "H1": candles[::4] if len(candles) >= 80 else candles,
    }


def test_engine_suite_smoke_flow() -> None:
    suite = create_engine_suite()
    candles = _build_multi_tf_candles()

    context = suite["context"].analyze(
        {
            "open": [c["open"] for c in candles["M15"]],
            "high": [c["high"] for c in candles["M15"]],
            "low": [c["low"] for c in candles["M15"]],
            "close": [c["close"] for c in candles["M15"]],
            "volume": [c["volume"] for c in candles["M15"]],
        }
    )

    coherence = suite["coherence"].evaluate(
        {
            "emotion_state": 0.7,
            "loss_stress": 0.2,
            "fatigue": 0.15,
        }
    )

    structure = suite["structure"].analyze(candles)
    direction = "BUY" if structure.structure_bias != "BEARISH" else "SELL"
    momentum = suite["momentum"].analyze(candles)
    precision = suite["precision"].analyze(candles, direction=direction)

    m15_close = candles["M15"][-1]["close"]
    risk = suite["risk_sim"].analyze(
        candles,
        direction=direction,
        entry_price=m15_close,
        stop_loss=m15_close - 0.0020,
        take_profit=m15_close + 0.0040,
    )

    field = suite["field"].analyze(candles)
    probability = suite["probability"].analyze(candles)
    advisory = suite["advisory"].analyze(
        {
            "structure": structure,
            "momentum": momentum,
            "precision": precision,
            "field": field,
            "coherence": coherence,
            "context": context,
            "risk_simulation": risk,
            "probability": probability,
        }
    )

    assert isinstance(context, CognitiveContext)
    assert isinstance(coherence, CoherenceSnapshot)
    assert isinstance(risk, RiskSimulationResult)
    assert isinstance(momentum, FusionMomentum)
    assert isinstance(precision, FusionPrecision)
    assert isinstance(structure, FusionStructure)
    assert isinstance(field, FieldResult)
    assert isinstance(probability, ProbabilityResult)
    assert isinstance(advisory, AdvisoryResult)

    assert structure.is_valid
    assert momentum.is_valid
    assert precision.is_valid
    assert field.is_valid
    assert probability.is_valid
    assert advisory.is_valid


def test_create_engine_suite_has_all_expected_engines() -> None:
    suite = create_engine_suite()
    expected = {
        "coherence",
        "context",
        "risk_sim",
        "risk",
        "momentum",
        "precision",
        "structure",
        "field",
        "probability",
        "advisory",
    }
    assert expected.issubset(set(suite.keys()))


def test_engines_evaluate_expected_contract_shapes() -> None:
    suite = create_engine_suite()
    candles = _build_multi_tf_candles(120)

    coherence = suite["coherence"].evaluate({"emotion_state": 0.5, "fatigue": 0.1, "loss_stress": 0.1})
    context = suite["context"].evaluate(
        {
            "trend_strength": 0.7,
            "volatility": 0.3,
            "structure_bias": 0.4,
            "liquidity_depth": 0.8,
            "institutional_flow": 0.75,
        }
    )
    structure = suite["structure"].analyze(candles)
    momentum = suite["momentum"].analyze(candles)
    precision = suite["precision"].analyze(candles, direction="BUY")
    probability = suite["probability"].analyze(candles)
    field = suite["field"].analyze(candles)
    risk = suite["risk"].analyze(
        candles,
        direction="BUY",
        entry_price=candles["M15"][-1]["close"],
        stop_loss=candles["M15"][-1]["close"] - 0.002,
        take_profit=candles["M15"][-1]["close"] + 0.004,
    )

    assert isinstance(coherence, CoherenceSnapshot)
    assert isinstance(context, CognitiveContext)
    assert isinstance(structure, FusionStructure)
    assert isinstance(momentum, FusionMomentum)
    assert isinstance(precision, FusionPrecision)
    assert isinstance(probability, ProbabilityResult)
    assert isinstance(field, FieldResult)
    assert isinstance(risk, RiskSimulationResult)


def test_risk_simulation_conservative_pass_fail_boundary() -> None:
    simulator = CognitiveRiskSimulation(num_simulations=200, horizon_bars=20, seed=7)

    safe_candles = _build_multi_tf_candles(140)
    base = safe_candles["M15"][-1]["close"]
    safe = simulator.analyze(
        safe_candles,
        direction="BUY",
        entry_price=base,
        stop_loss=base - 0.0015,
        take_profit=base + 0.0030,
    )

    volatile_series = [1.20 + (0.0015 * i) + (0.0100 if i % 2 == 0 else -0.0100) for i in range(140)]
    volatile_candles = {
        "M15": [
            {
                "open": volatile_series[i - 1] if i > 0 else volatile_series[i],
                "high": volatile_series[i] + 0.003,
                "low": volatile_series[i] - 0.003,
                "close": volatile_series[i],
                "volume": 1200,
            }
            for i in range(140)
        ]
    }
    vbase = volatile_candles["M15"][-1]["close"]
    unsafe = simulator.analyze(
        volatile_candles,
        direction="BUY",
        entry_price=vbase,
        stop_loss=vbase - 0.0015,
        take_profit=vbase + 0.0030,
    )

    assert safe.is_valid
    assert unsafe.is_valid
    assert unsafe.volatility_pct >= safe.volatility_pct
