import math

from engines import QuantumFieldEngine


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
        candles.append({"open": o, "high": h, "low": l, "close": c, "volume": v, "timestamp": i})
    return {"M15": candles}


def test_quantum_field_engine_rejects_empty_input() -> None:
    """Empty candle dict -> invalid result with error metadata."""
    engine = QuantumFieldEngine()
    result = engine.analyze({})

    assert not result.is_valid
    assert result.metadata.get("error") == "no_candles"


def test_quantum_field_engine_emits_metrics() -> None:
    """Sufficient multi-TF candles -> valid field analysis result."""
    engine = QuantumFieldEngine()
    result = engine.analyze(_make_candles(50), symbol="EURUSD")

    assert result.is_valid
    assert result.confidence > 0.0
    assert 0.0 <= result.energy_score <= 1.0
    assert result.volatility_regime in {"LOW", "NORMAL", "HIGH", "EXTREME"}
    assert result.field_polarity in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert isinstance(result.momentum_flux, float)
    assert isinstance(result.atr_normalized, float)
    assert isinstance(result.volume_energy, float)
    assert isinstance(result.price_velocity, float)
    assert isinstance(result.price_acceleration, float)
    assert isinstance(result.timeframe_scores, dict)
    assert "M15" in result.timeframe_scores
    assert result.metadata.get("symbol") == "EURUSD"


def test_quantum_field_engine_short_input_low_energy() -> None:
    """Very few candles (< 5 per TF) -> energy_score is 0.0."""
    engine = QuantumFieldEngine()
    short_candles = {
        "M15": [{"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 100, "timestamp": i} for i in range(3)]
    }
    result = engine.analyze(short_candles)

    # With < 5 candles, the single-TF analysis returns energy=0
    assert result.energy_score == 0.0


def test_quantum_field_engine_multi_tf() -> None:
    """Multiple timeframes -> mtf_alignment and timeframe_scores populated."""
    engine = QuantumFieldEngine()
    m15_candles = _make_candles(50)["M15"]
    h1_candles = _make_candles(30, start=100.0)["M15"]  # reuse helper

    candles = {"M15": m15_candles, "H1": h1_candles}
    result = engine.analyze(candles, symbol="USDJPY")

    assert result.is_valid
    assert "M15" in result.timeframe_scores
    assert "H1" in result.timeframe_scores
    assert 0.0 <= result.mtf_alignment <= 1.0
