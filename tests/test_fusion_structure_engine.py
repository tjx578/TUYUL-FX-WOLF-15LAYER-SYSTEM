from engines import FusionStructureEngine, StructureState


def test_returns_insufficient_data_when_series_short() -> None:
    engine = FusionStructureEngine()

    result = engine.analyze({"closes": [1.0] * 10})

    assert result.structure_state == StructureState.RANGE_BOUND
    assert result.details["reason"] == "insufficient_data"


def test_detects_bullish_divergence() -> None:
    engine = FusionStructureEngine()

    closes = [100 + i * 0.1 for i in range(30)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    lows[-1] = min(lows[-15:-5]) - 0.1
    rsi = [40.0 for _ in range(30)]
    rsi[-1] = min(rsi[-15:-5]) + 5.0

    result = engine.analyze(
        {
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "volumes": [1000.0] * 30,
            "rsi": rsi,
        }
    )

    assert result.divergence_present is True
    assert result.divergence_type == "BULLISH"


def test_exports_structure_payload() -> None:
    engine = FusionStructureEngine()

    result = engine.analyze(
        {
            "divergence": True,
            "divergence_type": "BEARISH",
            "liquidity_state": "LOW",
            "mtf_alignment": -0.2,
        }
    )

    payload = engine.export(result)
    assert payload["divergence_present"] is True
    assert payload["structure_state"] == StructureState.RANGE_BOUND.value
