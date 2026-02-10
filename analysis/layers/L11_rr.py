"""
L11 — Risk Reward Calculation

Calculates entry, stop loss, and take profit levels using
ATR for volatility-based stops and Fibonacci for targets.
"""

from typing import Dict, Optional

from analysis.market.fibonacci import FibonacciEngine
from analysis.market.indicators import IndicatorEngine
from context.live_context_bus import LiveContextBus


class L11RRAnalyzer:
    """
    Risk/Reward analyzer using ATR and Fibonacci.
    
    Wolf 30-Point discipline requires RR >= 1.5.
    """
    
    MIN_RR_RATIO = 1.5  # Minimum acceptable risk/reward ratio
    
    def __init__(self) -> None:
        self.context_bus = LiveContextBus()
        self.fib_engine = FibonacciEngine()
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
        history = self.context_bus.get_candle_history(symbol, "H1", count=14)
        
        if len(history) < 14:
            return {
                "valid": False,
                "reason": "insufficient_candle_history",
            }
        
        # Extract price data
        highs = [c["high"] for c in history]
        lows = [c["low"] for c in history]
        closes = [c["close"] for c in history]
        
        # Use current price as entry if not specified
        if entry is None:
            entry = closes[-1]
        
        # Calculate ATR for stop loss
        atr = self.indicator_engine.atr(highs, lows, closes, period=14)
        
        if atr is None or atr == 0:
            return {
                "valid": False,
                "reason": "atr_calculation_failed",
            }
        
        # Get recent swing high/low for Fibonacci
        swing_high = max(highs[-10:])
        swing_low = min(lows[-10:])
        
        # Calculate Fibonacci levels
        fib_levels = self.fib_engine.retracement(swing_high, swing_low)
        fib_extensions = self.fib_engine.extension(swing_high, swing_low)
        
        # Calculate stop loss and take profit based on direction
        if direction == "BUY":
            # Stop loss: Entry - (1.5 * ATR)
            stop_loss = entry - (1.5 * atr)
            
            # Take profit: Use Fibonacci extension 1.618
            take_profit = fib_extensions.get("1.618", entry + (3 * atr))
        
        elif direction == "SELL":
            # Stop loss: Entry + (1.5 * ATR)
            stop_loss = entry + (1.5 * atr)
            
            # Take profit: Use Fibonacci extension (inverse)
            tp_distance = swing_high - fib_extensions.get("1.618", swing_low)
            take_profit = entry - tp_distance
        
        else:
            return {
                "valid": False,
                "reason": "invalid_direction",
            }
        
        # Calculate risk and reward
        risk = abs(entry - stop_loss)
        reward = abs(take_profit - entry)
        
        if risk == 0:
            return {
                "valid": False,
                "reason": "zero_risk",
            }
        
        rr_ratio = round(reward / risk, 2)
        
        # Check if RR meets minimum requirement
        is_valid = rr_ratio >= self.MIN_RR_RATIO
        
        return {
            "entry": round(entry, 5),
            "stop_loss": round(stop_loss, 5),
            "take_profit": round(take_profit, 5),
            "risk": round(risk, 5),
            "reward": round(reward, 5),
            "rr": rr_ratio,
            "atr": round(atr, 5),
            "valid": is_valid,
            "reason": None if is_valid else f"rr_too_low_{rr_ratio}",
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
