import math

from engines import FusionPrecisionEngine


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


def test_precision_no_direction_returns_empty():
    """Direction='NONE' -> empty / invalid result."""
    engine = FusionPrecisionEngine()
    result = engine.analyze(_make_candles(40), direction="NONE")

    assert not result.is_valid
    assert result.confidence == 0.0
    assert result.metadata.get("error") == "no_candles_or_direction"


def test_precision_insufficient_candles():
    """Fewer than 20 candles -> insufficient result."""
    engine = FusionPrecisionEngine()
    result = engine.analyze(_make_candles(10), direction="BUY")

    assert not result.is_valid
    assert result.metadata.get("error") == "insufficient_candles"


def test_precision_buy_direction_computes_zones():
    """BUY direction with enough data -> valid precision zones and Fib levels."""
    engine = FusionPrecisionEngine()
    result = engine.analyze(_make_candles(50), direction="BUY", symbol="EURUSD")

    assert result.is_valid
    assert result.direction == "BUY"
    assert result.entry_optimal > 0
    assert result.stop_loss > 0
    assert result.stop_loss < result.entry_optimal  # SL below entry for BUY
    assert result.tp1 > result.entry_optimal         # TP above entry for BUY
    assert result.tp2 > result.tp1
    assert result.sl_method == "ATR"
    assert result.risk_reward_1 > 0
    assert result.risk_reward_2 > 0
    assert result.confidence > 0.0
    assert len(result.zones) > 0
    assert len(result.fib_levels) > 0
    assert result.metadata.get("symbol") == "EURUSD"


def test_precision_sell_direction_computes_zones():
    """SELL direction with enough data -> valid precision zones."""
    engine = FusionPrecisionEngine()
    result = engine.analyze(_make_candles(50), direction="SELL", symbol="GBPUSD")

    assert result.is_valid
    assert result.direction == "SELL"
    assert result.entry_optimal > 0
    assert result.stop_loss > result.entry_optimal  # SL above entry for SELL
    assert result.tp1 < result.entry_optimal         # TP below entry for SELL
    assert result.sl_method == "ATR"
    assert result.confidence > 0.0


def test_precision_result_has_expected_fields():
    """Result dataclass exposes all required fields."""
    engine = FusionPrecisionEngine()
    result = engine.analyze(_make_candles(50), direction="BUY")

    # Verify all structural fields are present and typed correctly
    assert isinstance(result.entry_zone_low, float)
    assert isinstance(result.entry_zone_high, float)
    assert isinstance(result.entry_optimal, float)
    assert isinstance(result.stop_loss, float)
    assert isinstance(result.sl_method, str)
    assert isinstance(result.tp1, float)
    assert isinstance(result.tp2, float)
    assert isinstance(result.tp3, float)
    assert isinstance(result.risk_reward_1, float)
    assert isinstance(result.risk_reward_2, float)
    assert isinstance(result.risk_reward_3, float)
    assert isinstance(result.zones, list)
    assert isinstance(result.fib_levels, dict)
    assert isinstance(result.precision_score, float)
    assert isinstance(result.confidence, float)
