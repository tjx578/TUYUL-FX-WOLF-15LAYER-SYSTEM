"""
L11 — Risk Reward Calculation

Calculates entry, stop loss, and take profit levels using
ATR for volatility-based stops and targets.
"""

from typing import Dict, Optional

from analysis.market.indicators import IndicatorEngine
from context.live_context_bus import LiveContextBus


class L11RRAnalyzer:
    """
    Risk/Reward analyzer using ATR for volatility-based calculations.

    Wolf 30-Point discipline requires RR >= 1.5.
    """

    MIN_RR_RATIO = 1.5  # Minimum acceptable risk/reward ratio

    def __init__(self) -> None:
        self.context_bus = LiveContextBus()
        self.indicator_engine = IndicatorEngine()

    def calculate_rr(
        self,
        symbol: str,
        direction: str,
        entry: Optional[float] = None,
    ) -> Dict:
        """
        Calculate risk/reward for a trade setup.

        Args:
            symbol: Trading pair symbol
            direction: "BUY" or "SELL"
            entry: Entry price (defaults to current price)

        Returns:
            Dictionary with RR calculation results
        """
        # Get H1 candle history for calculations
        history = self.context_bus.get_candle_history(symbol, "H1", count=20)

        if len(history) < 14:
            return {
                "valid": False,
                "reason": "no_data",
            }

        # Extract price data
        highs = [c["high"] for c in history]
        lows = [c["low"] for c in history]
        closes = [c["close"] for c in history]

        # Use current price as entry if not specified
        if entry is None:
            entry = float(closes[-1])

        # Calculate ATR for stop loss
        atr = self.indicator_engine.atr(highs, lows, closes, period=14)

        if atr is None or atr == 0:
            # Fallback: use simple high-low range
            atr = (max(highs[-20:]) - min(lows[-20:])) / 20
            if atr == 0:
                return {
                    "valid": False,
                    "reason": "no_data",
                }

        # Calculate stop loss and take profit based on direction
        if direction == "BUY":
            # Stop loss: Entry - (1.5 * ATR)
            sl = entry - (1.5 * atr) # pyright: ignore[reportOptionalOperand]
            # Take profit: Entry + (3.0 * ATR) for 2:1 RR minimum
            tp1 = entry + (3.0 * atr) # pyright: ignore[reportOptionalOperand]

        elif direction == "SELL":
            # Stop loss: Entry + (1.5 * ATR)
            sl = entry + (1.5 * atr) # pyright: ignore[reportOptionalOperand]
            # Take profit: Entry - (3.0 * ATR) for 2:1 RR minimum
            tp1 = entry - (3.0 * atr) # pyright: ignore[reportOptionalOperand]

        else:
            return {
                "valid": False,
                "reason": "invalid_direction",
            }

        # Calculate risk and reward
        risk = abs(entry - sl) # pyright: ignore[reportOptionalOperand]
        reward = abs(tp1 - entry) # pyright: ignore[reportOperatorIssue]

        if risk == 0:
            return {
                "valid": False,
                "reason": "no_data",
            }

        rr_ratio = round(reward / risk, 2)

        # Check if RR meets minimum requirement
        is_valid = rr_ratio >= self.MIN_RR_RATIO
        reason = "rr_ok" if is_valid else "rr_too_low"

        # Narrow types for pyright — entry/sl/tp1/atr are guaranteed non-None here
        assert entry is not None
        assert sl is not None
        assert tp1 is not None
        assert atr is not None

        return {
            "valid": is_valid,
            "rr": rr_ratio,
            "entry": round(entry, 5),
            "sl": round(sl, 5),
            "tp1": round(tp1, 5),
            "direction": direction,
            "atr": round(atr, 5),
            "reason": reason,
        }

    def calculate(
        self,
        entry: Optional[float],
        sl: Optional[float],
        tp: Optional[float],
    ) -> Dict:
        """
        Calculate RR from explicit entry/SL/TP values.

        Legacy method for backward compatibility.

        Args:
            entry: Entry price
            sl: Stop loss price
            tp: Take profit price

        Returns:
            Dictionary with RR results
        """
        if entry is None or sl is None or tp is None:
            return {"valid": False}

        risk = abs(entry - sl)
        reward = abs(tp - entry)

        if risk == 0:
            return {"valid": False}

        rr = round(reward / risk, 2)

        return {
            "entry": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "rr": rr,
            "valid": rr >= self.MIN_RR_RATIO,
        }
