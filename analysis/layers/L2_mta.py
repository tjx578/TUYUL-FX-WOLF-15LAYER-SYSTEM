"""
L2 — Multi-Timeframe Alignment (W1 → D1 → H4 → H1 → M15)

Hierarchical weighted confluence model.
Higher timeframes have dominant weight.
"""

from context.live_context_bus import LiveContextBus

# Timeframe weights — higher TF = higher authority
TF_WEIGHTS: dict[str, float] = {
    "W1": 0.30,
    "D1": 0.20,
    "H4": 0.20,
    "H1": 0.15,
    "M15": 0.15,
}

ALIGNMENT_THRESHOLD: float = 0.3  # Minimum composite bias for directional signal


class L2MTAAnalyzer:
    def __init__(self) -> None:
        self.context = LiveContextBus()

    def analyze(self, symbol: str) -> dict:
        """Analyze multi-timeframe alignment for a symbol."""
        biases: dict[str, int] = {}
        tf_data: dict[str, dict | None] = {}

        for tf in TF_WEIGHTS:
            candle = self.context.get_candle(symbol, tf)
            tf_data[tf] = candle
            if candle and candle.get("open") is not None and candle.get("close") is not None:
                if candle["close"] > candle["open"]:
                    biases[tf] = 1  # Bullish
                elif candle["close"] < candle["open"]:
                    biases[tf] = -1  # Bearish
                else:
                    biases[tf] = 0  # Neutral (doji)
            else:
                biases[tf] = 0

        # Compute weighted composite bias
        composite_bias: float = sum(
            biases[tf] * weight for tf, weight in TF_WEIGHTS.items()
        )

        # Count available timeframes
        available_tfs = sum(1 for tf in TF_WEIGHTS if tf_data[tf] is not None)

        # Determine alignment
        if composite_bias > ALIGNMENT_THRESHOLD:
            direction = "BULLISH"
        elif composite_bias < -ALIGNMENT_THRESHOLD:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        # Full alignment check (all available TFs agree)
        non_zero_biases = [b for b in biases.values() if b != 0]
        fully_aligned = (
            len(non_zero_biases) >= 3
            and all(b > 0 for b in non_zero_biases)
            or all(b < 0 for b in non_zero_biases)
        )

        return {
            "aligned": fully_aligned,
            "valid": available_tfs >= 2,  # Need at least 2 TFs
            "direction": direction,
            "composite_bias": round(composite_bias, 4),
            "alignment_strength": round(abs(composite_bias), 4),
            "available_timeframes": available_tfs,
            "per_tf_bias": biases,
        }

