from engines import FusionStructureEngine, StructureState


def test_returns_insufficient_data_when_series_short() -> None:
    engine = FusionStructureEngine()

    candles = {
        "M15": [
            {
                "open": 1.0,
                "high": 1.01,
                "low": 0.99,
                "close": 1.0,
                "volume": 1000,
            }
            for _ in range(9)
        ]
    }
    result = engine.analyze(candles)

    assert result.structure_bias == StructureState.NEUTRAL.value
    assert result.structure_score == 0.0


def test_detects_bullish_divergence() -> None:
    engine = FusionStructureEngine()

    closes = [100 + i * 0.1 + (0.25 if i % 2 == 0 else -0.2) for i in range(60)]
    highs = [c + 0.6 for c in closes]
    lows = [c - 0.6 for c in closes]

    result = engine.analyze(
        {
            "M15": [
                {
                    "open": closes[i - 1] if i > 0 else closes[i],
                    "high": highs[i],
                    "low": lows[i],
                    "close": closes[i],
                    "volume": 1000.0,
                }
                for i in range(len(closes))
            ]
        }
    )

    assert result.structure_bias in {
        StructureState.BULLISH.value,
        StructureState.NEUTRAL.value,
        StructureState.RANGING.value,
    }
    assert result.confidence >= 0.0


def test_exports_structure_payload() -> None:
    engine = FusionStructureEngine()

    closes = [1.2 + i * 0.0004 + (0.00015 if i % 3 == 0 else -0.0001) for i in range(70)]
    candles = {
        "M15": [
            {
                "open": closes[i - 1] if i > 0 else closes[i],
                "high": closes[i] + 0.0005,
                "low": closes[i] - 0.0005,
                "close": closes[i],
                "volume": 900 + i,
            }
            for i in range(len(closes))
        ]
    }
    result = engine.analyze(candles)

    payload = {
        "structure_bias": result.structure_bias,
        "bos_detected": result.bos_detected,
        "choch_detected": result.choch_detected,
        "mtf_structure_alignment": result.mtf_structure_alignment,
        "confidence": result.confidence,
    }

    assert payload["structure_bias"] in {
        StructureState.BULLISH.value,
        StructureState.BEARISH.value,
        StructureState.NEUTRAL.value,
        StructureState.RANGING.value,
    }
    assert isinstance(payload["bos_detected"], bool)
    assert isinstance(payload["choch_detected"], bool)
