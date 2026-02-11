"""
L9 — Smart Money Concept (SMC)

Analyzes market structure for liquidity sweeps, displacement,
and Break of Structure (BOS) detection.
"""

from loguru import logger

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
        self._previous_trend = {}  # Track previous trend for CHoCH detection

    def analyze(self, symbol: str, structure: dict) -> dict:
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

        # Add monthly, weekly and H4 structure analysis
        monthly_structure = self._monthly_structure(symbol)
        monthly_sweep = self._monthly_liquidity_sweep(symbol)
        weekly_structure = self._weekly_structure(symbol)
        weekly_sweep = self._weekly_liquidity_sweep(symbol)
        h4_structure = self._h4_structure(symbol)

        # Add weekly bias conflict detection
        smc_conflict = False
        direction = None
        if trend == "BULLISH":
            direction = "BUY"
        elif trend == "BEARISH":
            direction = "SELL"

        if weekly_structure.get("state") == "BULLISH_STRUCTURE" and direction == "SELL":
            smc_conflict = True
        elif weekly_structure.get("state") == "BEARISH_STRUCTURE" and direction == "BUY":
            smc_conflict = True

        if smc_conflict and "confidence" in smc:
            smc["confidence"] = round(smc["confidence"] * 0.6, 2)

        # Add monthly bias conflict detection (stronger penalty)
        smc_monthly_conflict = False
        if monthly_structure.get("state") == "BULLISH_STRUCTURE" and direction == "SELL":
            smc_monthly_conflict = True
        elif monthly_structure.get("state") == "BEARISH_STRUCTURE" and direction == "BUY":
            smc_monthly_conflict = True

        if smc_monthly_conflict and "confidence" in smc:
            smc["confidence"] = round(smc["confidence"] * 0.5, 2)

        # Stacking rule: MN sweep + W1 sweep + H4 BOS = confidence boost
        # But only if directionally aligned (all bullish or all bearish)
        mn_sweep = monthly_sweep.get("sweep") is not None
        w1_sweep = weekly_sweep.get("sweep") is not None
        h4_bos = h4_structure.get("state") in ("BULLISH_BOS", "BEARISH_BOS")

        if mn_sweep and w1_sweep and h4_bos:
            # Check directional consistency
            mn_sweep_type = monthly_sweep.get("sweep")
            w1_sweep_type = weekly_sweep.get("sweep")
            h4_state = h4_structure.get("state")

            # SELL_SIDE_TAKEN (bullish sweep) + BULLISH_BOS = aligned bullish
            # BUY_SIDE_TAKEN (bearish sweep) + BEARISH_BOS = aligned bearish
            bullish_aligned = (
                mn_sweep_type == "SELL_SIDE_TAKEN"
                and w1_sweep_type == "SELL_SIDE_TAKEN"
                and h4_state == "BULLISH_BOS"
            )
            bearish_aligned = (
                mn_sweep_type == "BUY_SIDE_TAKEN"
                and w1_sweep_type == "BUY_SIDE_TAKEN"
                and h4_state == "BEARISH_BOS"
            )

            if bullish_aligned or bearish_aligned:
                smc["confidence"] = min(round(smc["confidence"] * 1.4, 2), 1.0)

        smc["monthly_structure"] = monthly_structure
        smc["monthly_sweep"] = monthly_sweep
        smc["weekly_structure"] = weekly_structure
        smc["weekly_sweep"] = weekly_sweep
        smc["h4_structure"] = h4_structure
        smc["smc_weekly_conflict"] = smc_conflict
        smc["smc_monthly_conflict"] = smc_monthly_conflict

        # Update previous trend for next call
        self._previous_trend[symbol] = trend

        return smc

    def _monthly_structure(self, symbol: str) -> dict:
        """Detect monthly market structure state."""
        mn_candles = self.context_bus.get_candle_history(symbol, "MN", count=3)

        if len(mn_candles) < 2:
            return {"state": "UNKNOWN", "valid": False}

        last = mn_candles[-1]
        prev = mn_candles[-2]

        if last["high"] > prev["high"] and last["low"] > prev["low"]:
            state = "BULLISH_STRUCTURE"
        elif last["high"] < prev["high"] and last["low"] < prev["low"]:
            state = "BEARISH_STRUCTURE"
        else:
            state = "RANGE"

        return {"state": state, "valid": True}

    def _monthly_liquidity_sweep(self, symbol: str) -> dict:
        """Detect monthly liquidity sweep."""
        mn_candles = self.context_bus.get_candle_history(symbol, "MN", count=3)

        if len(mn_candles) < 2:
            return {"sweep": None, "valid": False}

        last = mn_candles[-1]
        prev = mn_candles[-2]

        # Buy-side liquidity taken (swept above prev high, closed below)
        if last["high"] > prev["high"] and last["close"] < prev["high"]:
            return {"sweep": "BUY_SIDE_TAKEN", "valid": True}

        # Sell-side liquidity taken (swept below prev low, closed above)
        if last["low"] < prev["low"] and last["close"] > prev["low"]:
            return {"sweep": "SELL_SIDE_TAKEN", "valid": True}

        return {"sweep": None, "valid": True}

    def _weekly_structure(self, symbol: str) -> dict:
        """Detect weekly market structure state."""
        w1_candles = self.context_bus.get_candle_history(symbol, "W1", count=3)

        if len(w1_candles) < 2:
            return {"state": "UNKNOWN", "valid": False}

        last = w1_candles[-1]
        prev = w1_candles[-2]

        if last["high"] > prev["high"] and last["low"] > prev["low"]:
            state = "BULLISH_STRUCTURE"
        elif last["high"] < prev["high"] and last["low"] < prev["low"]:
            state = "BEARISH_STRUCTURE"
        else:
            state = "RANGE"

        return {"state": state, "valid": True}

    def _weekly_liquidity_sweep(self, symbol: str) -> dict:
        """Detect weekly liquidity sweep."""
        w1_candles = self.context_bus.get_candle_history(symbol, "W1", count=3)

        if len(w1_candles) < 2:
            return {"sweep": None, "valid": False}

        last = w1_candles[-1]
        prev = w1_candles[-2]

        # Buy-side liquidity taken (swept above prev high, closed below)
        if last["high"] > prev["high"] and last["close"] < prev["high"]:
            return {"sweep": "BUY_SIDE_TAKEN", "valid": True}

        # Sell-side liquidity taken (swept below prev low, closed above)
        if last["low"] < prev["low"] and last["close"] > prev["low"]:
            return {"sweep": "SELL_SIDE_TAKEN", "valid": True}

        return {"sweep": None, "valid": True}

    def _h4_structure(self, symbol: str) -> dict:
        """Detect H4 market structure."""
        h4_candles = self.context_bus.get_candle_history(symbol, "H4", count=5)

        if len(h4_candles) < 2:
            return {"state": "UNKNOWN", "valid": False}

        last = h4_candles[-1]
        prev = h4_candles[-2]

        if last["high"] > prev["high"]:
            state = "BULLISH_BOS"
        elif last["low"] < prev["low"]:
            state = "BEARISH_BOS"
        else:
            state = "RANGE"

        return {"state": state, "valid": True}

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
        if current_trend == "BEARISH":
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
        if prev_trend == "BEARISH" and current_trend == "BULLISH":
            logger.info(f"CHoCH detected for {symbol}: BEARISH → BULLISH")
            return True

        return False
