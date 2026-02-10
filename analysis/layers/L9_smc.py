"""
L9 — Smart Money Concept (SMC)

Analyzes market structure for liquidity sweeps, displacement,
and Break of Structure (BOS) detection.
"""

from typing import Dict

from loguru import logger

from analysis.market.structure import MarketStructureAnalyzer
from context.live_context_bus import LiveContextBus


class L9SMCAnalyzer:
    """
    Smart Money Concept analyzer.
    
    Uses market structure analysis to detect:
    - Break of Structure (BOS)
    - Change of Character (CHoCH)
    - Liquidity sweeps (placeholder)
    - Displacement (strong momentum moves)
    """
    
    def __init__(self) -> None:
        self.context_bus = LiveContextBus()
        self.structure_analyzer = MarketStructureAnalyzer()
        self._previous_trend = {}  # Track previous trend for CHoCH detection
    
    def analyze(self, symbol: str, structure: Dict) -> Dict:
        """
        Analyze Smart Money Concepts based on market structure.
        
        Args:
            symbol: Trading pair symbol
            structure: Output from MarketStructureAnalyzer
            
        Returns:
            Dictionary with SMC analysis results
        """
        if not structure or not structure.get("valid"):
            return {"valid": False, "reason": "no_structure_data"}

        trend = structure.get("trend", "NEUTRAL")
        
        # Detect BOS (Break of Structure)
        bos_detected = self._detect_bos(symbol, trend)
        
        # Detect CHoCH (Change of Character)
        choch_detected = self._detect_choch(symbol, trend)
        
        # Base SMC output
        smc = {
            "smc": trend != "NEUTRAL" and (bos_detected or choch_detected),
            "bos_detected": bos_detected,
            "choch_detected": choch_detected,
            "liquidity_sweep": False,  # Placeholder for future implementation
            "displacement": False,  # Placeholder for future implementation
            "confidence": 0.3,  # Default low confidence
            "valid": True,
        }

        # Confidence scoring based on structure quality
        if bos_detected and trend != "NEUTRAL":
            # BOS with clear trend = high confidence
            smc["confidence"] = 0.8
            smc["displacement"] = True
        elif choch_detected:
            # CHoCH = reversal signal, medium confidence
            smc["confidence"] = 0.6
        elif trend != "NEUTRAL":
            # Clear trend but no BOS/CHoCH
            smc["confidence"] = 0.5
        
        # Update previous trend for next call
        self._previous_trend[symbol] = trend

        return smc
    
    def _detect_bos(self, symbol: str, current_trend: str) -> bool:
        """
        Detect Break of Structure (BOS).
        
        BOS occurs when price breaks a previous swing high (bullish)
        or swing low (bearish) in the direction of the trend.
        
        Args:
            symbol: Trading pair symbol
            current_trend: Current market trend
            
        Returns:
            True if BOS detected, False otherwise
        """
        if current_trend == "NEUTRAL":
            return False
        
        # Get H1 candle history
        history = self.context_bus.get_candle_history(symbol, "H1", count=20)
        
        if len(history) < 5:
            return False
        
        # Get current candle
        current = history[-1]
        current_close = current["close"]
        
        # Get recent swing points
        highs = [c["high"] for c in history[:-1]]  # Exclude current
        lows = [c["low"] for c in history[:-1]]
        
        if len(highs) < 4:
            return False
        
        # Find previous swing high/low
        prev_swing_high = max(highs[-10:]) if len(highs) >= 10 else max(highs)
        prev_swing_low = min(lows[-10:]) if len(lows) >= 10 else min(lows)
        
        # Bullish BOS: current close breaks above previous swing high
        if current_trend == "BULLISH":
            return current_close > prev_swing_high
        
        # Bearish BOS: current close breaks below previous swing low
        elif current_trend == "BEARISH":
            return current_close < prev_swing_low
        
        return False
    
    def _detect_choch(self, symbol: str, current_trend: str) -> bool:
        """
        Detect Change of Character (CHoCH).
        
        CHoCH occurs when the trend structure changes:
        - Was BULLISH (HH+HL) but now making LH+LL
        - Was BEARISH (LH+LL) but now making HH+HL
        
        Args:
            symbol: Trading pair symbol
            current_trend: Current market trend
            
        Returns:
            True if CHoCH detected, False otherwise
        """
        # Get previous trend for this symbol
        prev_trend = self._previous_trend.get(symbol, "NEUTRAL")
        
        # CHoCH detected if trend changed from bullish to bearish or vice versa
        if prev_trend == "BULLISH" and current_trend == "BEARISH":
            logger.info(f"CHoCH detected for {symbol}: BULLISH → BEARISH")
            return True
        elif prev_trend == "BEARISH" and current_trend == "BULLISH":
            logger.info(f"CHoCH detected for {symbol}: BEARISH → BULLISH")
            return True
        
        return False
