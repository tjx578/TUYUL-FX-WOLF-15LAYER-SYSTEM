"""
Volatility analysis utilities.

Provides ATR calculation and volatility regime detection
for multi-timeframe risk adjustment.
"""

from __future__ import annotations

from typing import Any


def calculate_atr(candles: list[dict], period: int = 14) -> float:
    """Calculate Average True Range from candle data.

    Args:
        candles: List of candle dicts with high, low, close keys.
        period: ATR period (default 14).

    Returns:
        ATR value. Returns 0.0 if insufficient data.
    """
    if len(candles) < 2:
        return 0.0

    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    if not true_ranges:
        return 0.0

    # Use last N periods
    recent = true_ranges[-period:]
    return sum(recent) / len(recent)


def volatility_regime(
    current_atr: float,
    baseline_atr: float,
) -> dict[str, Any]:
    """Determine volatility regime from ATR ratio.

    Args:
        current_atr: Current period ATR.
        baseline_atr: Baseline (rolling mean) ATR.

    Returns:
        Dict with regime, ratio, and adjustment factors.
    """
    if baseline_atr <= 0:
        return {
            "regime": "UNKNOWN",
            "ratio": 0.0,
            "confidence_multiplier": 1.0,
            "risk_multiplier": 1.0,
        }

    ratio = current_atr / baseline_atr

    if ratio > 1.5:
        regime = "EXPANSION"
        confidence_mult = 0.9
        risk_mult = 0.8  # Reduce position size in high vol
    elif ratio < 0.7:
        regime = "COMPRESSION"
        confidence_mult = 0.95
        risk_mult = 1.0
    else:
        regime = "NORMAL"
        confidence_mult = 1.0
        risk_mult = 1.0

    return {
        "regime": regime,
        "ratio": round(ratio, 4),
        "confidence_multiplier": confidence_mult,
        "risk_multiplier": risk_mult,
    }
