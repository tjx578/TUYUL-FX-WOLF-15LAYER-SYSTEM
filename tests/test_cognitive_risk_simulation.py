import math

from engines import CognitiveRiskSimulation


def _make_candles(n: int = 50, start: float = 100.0) -> dict:
    """Generate multi-TF candle dict with oscillating price for testing."""
    candles = []
    for i in range(n):
        mid = start + i * 0.01 + 3.0 * math.sin(2 * math.pi * i / 20.0)
        o = mid
        c = mid + 0.05
        h = max(o, c) + 0.5
        l = min(o, c) - 0.5  # noqa: E741
        v = 1000 + (i % 9) * 80
        candles.append(
            {"open": o, "high": h, "low": l, "close": c, "volume": v, "timestamp": i}
        )
    return {"M15": candles}


def test_analyze_insufficient_when_no_direction() -> None:
    """No direction provided -> insufficient result."""
    simulator = CognitiveRiskSimulation(seed=123)
    result = simulator.analyze(_make_candles(30), direction="NONE")

    assert result.confidence == 0.0
    assert result.simulations_run == 0
    assert not result.is_valid
    assert result.metadata.get("error") == "no_data_or_direction"


def test_analyze_insufficient_when_empty_candles() -> None:
    """Empty candle dict -> insufficient result."""
    simulator = CognitiveRiskSimulation(seed=123)
    result = simulator.analyze({}, direction="BUY")

    assert not result.is_valid
    assert result.metadata.get("error") == "no_data_or_direction"


def test_analyze_insufficient_when_few_candles() -> None:
    """Fewer than 20 candles -> insufficient result."""
    simulator = CognitiveRiskSimulation(seed=123)
    result = simulator.analyze(_make_candles(10), direction="BUY")

    assert not result.is_valid
    assert result.metadata.get("error") == "insufficient_candles"


def test_analyze_partial_result_when_no_sl_tp() -> None:
    """Enough data but no SL/TP -> partial result with low confidence."""
    simulator = CognitiveRiskSimulation(num_simulations=200, seed=7)
    result = simulator.analyze(_make_candles(50), direction="BUY")

    assert result.confidence == 0.3
    assert result.metadata.get("note") == "no_sl_tp_provided"
    assert result.risk_class == "MODERATE"


def test_analyze_produces_valid_result_with_sl_tp() -> None:
    """Full parameters -> valid simulation result."""
    simulator = CognitiveRiskSimulation(num_simulations=200, seed=7)
    candles = _make_candles(50)
    last_close = candles["M15"][-1]["close"]

    result = simulator.analyze(
        candles,
        direction="BUY",
        entry_price=last_close,
        stop_loss=last_close - 2.0,
        take_profit=last_close + 4.0,
        symbol="EURUSD",
    )

    assert result.is_valid
    assert result.simulations_run == 200
    assert result.confidence > 0.0
    assert 0.0 <= result.win_probability <= 1.0
    assert 0.0 <= result.loss_probability <= 1.0
    assert result.risk_class in {"LOW", "MODERATE", "HIGH", "EXTREME"}
    assert 0.0 <= result.risk_score <= 1.0
    assert result.expected_rr > 0.0
    assert result.metadata.get("symbol") == "EURUSD"
    assert len(result.scenario_results) <= 10  # capped at top 10
