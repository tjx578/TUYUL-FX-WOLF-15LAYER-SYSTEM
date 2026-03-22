import math
from types import SimpleNamespace

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
    """When coherence_verdict='ABORT', advisory action should be ABORT."""
    suite = create_engine_suite()
    advisory = suite["advisory"]
    result = advisory.analyze(  # type: ignore[attr-defined]
        {
            "field": SimpleNamespace(energy_score=0.5, field_polarity="BULLISH"),
            "probability": SimpleNamespace(confidence=0.7),
            "coherence": SimpleNamespace(
                coherence_score=0.3,
                coherence_verdict="ABORT",
                coherence_index=0.5,
            ),
        }
    )
    assert result.advisory_action == "ABORT"
    assert any("ABORT" in r for r in result.reasons)


def _make_candles(n: int = 160, start: float = 100.0) -> dict:
    """Generate multi-TF candle dict with oscillating price for testing."""
    candles = []
    for i in range(n):
        mid = start + i * 0.01 + 3.0 * math.sin(2 * math.pi * i / 20.0)
        o = mid
        c = mid + 0.05
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5  # noqa: E741
        v = 1000 + (i % 9) * 80
        candles.append({"open": o, "high": h, "low": l, "close": c, "volume": v, "timestamp": i})
    return {"M15": candles}


def test_engine_suite_runs_end_to_end():
    """Test end-to-end engine orchestration with realistic multi-regime data."""
    suite = create_engine_suite()
    candles = _make_candles(160)

    # Extract raw lists for context engine (takes raw list-based snapshot)
    raw = candles["M15"]
    closes = [c["close"] for c in raw]
    highs = [c["high"] for c in raw]
    lows = [c["low"] for c in raw]
    volumes = [c["volume"] for c in raw]

    context = suite["context"].analyze(  # type: ignore[attr-defined]
        {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}
    )
    coherence = suite["coherence"].evaluate(  # type: ignore[attr-defined]
        {"emotion_state": 0.15, "fatigue": 0.2, "loss_stress": 0.1},
        market_volatility=0.01,
    )
    field = suite["field"].analyze(candles)  # type: ignore[attr-defined]
    momentum = suite["momentum"].analyze(candles)  # type: ignore[attr-defined]
    precision = suite["precision"].analyze(candles, direction="BUY")  # type: ignore[attr-defined]
    structure = suite["structure"].analyze(candles)  # type: ignore[attr-defined]
    probability = suite["probability"].analyze(candles)  # type: ignore[attr-defined]

    # Risk simulation uses precision's entry/sl/tp when available
    entry = precision.entry_optimal if precision.is_valid else closes[-1]
    sl = precision.stop_loss if precision.is_valid else entry - 2.0
    tp = precision.tp1 if precision.is_valid else entry + 4.0
    risk_sim = suite["risk"].analyze(  # type: ignore[attr-defined]
        candles,
        direction="BUY",
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
    )

    advisory = suite["advisory"].analyze(  # type: ignore[attr-defined]
        {
            "structure": structure,
            "momentum": momentum,
            "precision": precision,
            "field": field,
            "coherence": coherence,
            "context": context,
            "risk_simulation": risk_sim,
            "probability": probability,
        },
        symbol="EURUSD",
    )

    assert probability.confidence >= 0.0
    assert advisory.advisory_action in {"EXECUTE", "HOLD", "NO_TRADE", "ABORT"}


def test_engine_suite_simple():
    """Test basic smoke test with simple data."""
    suite = create_engine_suite()
    candles = _make_candles(80)

    raw = candles["M15"]
    closes = [c["close"] for c in raw]
    highs = [c["high"] for c in raw]
    lows = [c["low"] for c in raw]
    volumes = [c["volume"] for c in raw]

    context = suite["context"].analyze(  # type: ignore[attr-defined]
        {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}
    )
    coherence = suite["coherence"].evaluate(  # type: ignore[attr-defined]
        {"emotion_state": 0.15, "fatigue": 0.2, "loss_stress": 0.1},
        market_volatility=0.01,
    )
    field = suite["field"].analyze(candles)  # type: ignore[attr-defined]

    assert context.market_regime in {"RISK_ON", "RISK_OFF", "TRANSITIONAL"}
    assert 0.0 <= coherence.coherence_index <= 1.0
    assert field.volatility_regime in {"LOW", "NORMAL", "HIGH", "EXTREME"}


def test_advisory_detects_lockout_conflict():
    """Advisory with coherence ABORT should return ABORT action."""
    suite = create_engine_suite()
    advisory = suite["advisory"]
    result = advisory.analyze(  # type: ignore[attr-defined]
        {
            "field": SimpleNamespace(energy_score=0.4, field_polarity="BULLISH"),
            "probability": SimpleNamespace(confidence=0.8),
            "coherence": SimpleNamespace(
                coherence_score=0.4,
                coherence_verdict="ABORT",
            ),
            "context": SimpleNamespace(context_score=0.6, context_verdict="NEUTRAL"),
            "momentum": SimpleNamespace(momentum_score=0.5, momentum_bias="BULLISH"),
            "precision": SimpleNamespace(
                precision_score=0.8,
                entry_optimal=1.10,
                stop_loss=1.09,
                tp1=1.12,
                risk_reward_1=2.0,
            ),
            "structure": SimpleNamespace(structure_score=0.7, structure_bias="BULLISH"),
            "risk_simulation": SimpleNamespace(risk_score=0.8, win_probability=0.65),
        }
    )
    assert result.advisory_action == "ABORT"
    assert any("ABORT" in r for r in result.reasons)
