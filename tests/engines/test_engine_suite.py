from types import SimpleNamespace
from typing import Any

from engines import create_engine_suite


def _make_candles(n: int = 60) -> dict[str, list[dict]]:
    """Generate multi-TF candle dict for engine smoke testing."""
    candles: list[dict] = []
    for i in range(n):
        o = 100.0 + i * 0.2
        candles.append({"open": o, "high": o + 0.3, "low": o - 0.1, "close": o + 0.1, "volume": 1000 + i})
    return {"M15": candles, "H1": candles[:30]}


def test_engine_suite_smoke() -> None:
    suite: dict[str, Any] = create_engine_suite()
    candles = _make_candles(60)

    context = suite["context"].analyze(candles=candles, symbol="EURUSD")
    field = suite["field"].analyze(candles=candles, symbol="EURUSD")
    momentum = suite["momentum"].analyze(candles=candles, direction="BUY", symbol="EURUSD")
    risk = suite["risk"].analyze(
        candles=candles, direction="BUY", entry_price=110.0, stop_loss=109.0, take_profit=112.0, symbol="EURUSD"
    )
    coherence = suite["coherence"].analyze(candles=candles, symbol="EURUSD")
    precision = suite["precision"].analyze(candles=candles, direction="BUY", symbol="EURUSD")
    structure = suite["structure"].analyze(candles=candles, direction="BUY", symbol="EURUSD")
    probability = suite["probability"].analyze(candles=candles, symbol="EURUSD")
    advisory = suite["advisory"].analyze(
        engine_outputs={
            "field": SimpleNamespace(energy=0.5, bias=0.3, entropy=0.2, coherence=0.4, signal="BUY"),
            "probability": SimpleNamespace(weighted_probability=0.6, layer_probabilities={}, confidence=0.5, signal="BUY"),
            "coherence": SimpleNamespace(coherence_index=0.7, state="COHERENT", risk_flag=False, signal="BUY"),
            "structure": SimpleNamespace(structure_score=0.5, trend="BULLISH", signal="BUY"),
        },
        symbol="EURUSD",
    )

    # Basic sanity: all results should be non-None
    assert context is not None
    assert field is not None
    assert momentum is not None
    assert risk is not None
    assert coherence is not None
    assert precision is not None
    assert structure is not None
    assert probability is not None
    assert advisory is not None
    assert advisory.signal in {"EXECUTE", "HOLD", "ABORT", "INSUFFICIENT"}
