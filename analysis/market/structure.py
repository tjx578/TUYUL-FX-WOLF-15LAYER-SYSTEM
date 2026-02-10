"""
Market Structure Analysis (H1)
NO EXECUTION | NO DECISION
"""

from typing import Dict, List

from context.live_context_bus import LiveContextBus


class MarketStructureAnalyzer:
    """
    Analyzes market structure using swing high/low detection.
    
    Detects trends based on Higher Highs/Higher Lows (BULLISH)
    or Lower Highs/Lower Lows (BEARISH).
    """
    
    def __init__(self) -> None:
        self.context = LiveContextBus()

    def analyze(self, symbol: str) -> Dict:
        """
        Analyze H1 market structure for a symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Dictionary with trend, BOS, CHoCH, and validity
        """
        candle = self.context.get_candle(symbol, "H1")
        if not candle:
            return {"valid": False, "reason": "no_h1_candle"}

        structure = {
            "trend": self._detect_trend(symbol),
            "bos": False,
            "choch": False,
            "valid": True,
        }

        return structure

    def _detect_trend(self, symbol: str) -> str:
        """
        Detect trend using swing high/low analysis.
        
        Algorithm:
        1. Get last 20 H1 candles
        2. Find swing highs and lows (local peaks/valleys)
        3. Compare recent swings to determine trend:
           - HH + HL = BULLISH (Higher Highs + Higher Lows)
           - LH + LL = BEARISH (Lower Highs + Lower Lows)
           - Otherwise = NEUTRAL
           
        Args:
            symbol: Trading pair symbol
            
        Returns:
            "BULLISH" | "BEARISH" | "NEUTRAL"
        """
        # Get candle history (need at least 5 candles for swing detection)
        history = self.context.get_candle_history(symbol, "H1", count=20)
        
        if len(history) < 5:
            return "NEUTRAL"
        
        # Extract highs and lows
        highs = [c["high"] for c in history]
        lows = [c["low"] for c in history]
        
        # Find swing points (peaks and valleys)
        swing_highs = self._find_swing_highs(highs)
        swing_lows = self._find_swing_lows(lows)
        
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return "NEUTRAL"
        
        # Compare most recent 2 swing highs
        recent_highs = swing_highs[-2:]
        is_higher_high = recent_highs[1] > recent_highs[0]
        is_lower_high = recent_highs[1] < recent_highs[0]
        
        # Compare most recent 2 swing lows
        recent_lows = swing_lows[-2:]
        is_higher_low = recent_lows[1] > recent_lows[0]
        is_lower_low = recent_lows[1] < recent_lows[0]
        
        # Determine trend
        if is_higher_high and is_higher_low:
            return "BULLISH"
        elif is_lower_high and is_lower_low:
            return "BEARISH"
        else:
            return "NEUTRAL"
    
    @staticmethod
    def _find_swing_highs(highs: List[float], window: int = 2) -> List[float]:
        """
        Find swing highs (local maxima) in price series.
        
        A swing high is a peak where the high is greater than
        N candles before and after it.
        
        Args:
            highs: List of high prices
            window: Number of candles to look before/after
            
        Returns:
            List of swing high values
        """
        swing_highs = []
        
        for i in range(window, len(highs) - window):
            is_peak = True
            
            # Check if this high is greater than surrounding candles
            for j in range(i - window, i + window + 1):
                if j != i and highs[j] >= highs[i]:
                    is_peak = False
                    break
            
            if is_peak:
                swing_highs.append(highs[i])
        
        return swing_highs
    
    @staticmethod
    def _find_swing_lows(lows: List[float], window: int = 2) -> List[float]:
        """
        Find swing lows (local minima) in price series.
        
        A swing low is a valley where the low is less than
        N candles before and after it.
        
        Args:
            lows: List of low prices
            window: Number of candles to look before/after
            
        Returns:
            List of swing low values
        """
        swing_lows = []
        
        for i in range(window, len(lows) - window):
            is_valley = True
            
            # Check if this low is less than surrounding candles
            for j in range(i - window, i + window + 1):
                if j != i and lows[j] <= lows[i]:
                    is_valley = False
                    break
            
            if is_valley:
                swing_lows.append(lows[i])
        
        return swing_lows
