"""
Context data validators for ticks, candles, and news.

Zone: context/ — pure validation, no side-effects.
"""

from __future__ import annotations

from loguru import logger  # pyright: ignore[reportMissingImports]

_REQUIRED_TICK_FIELDS = {"symbol", "bid", "ask", "timestamp"}
_REQUIRED_CANDLE_FIELDS = {"symbol", "timeframe", "open", "high", "low", "close", "timestamp"}


class ContextValidator:
    """Validates context data structures before storage."""

    @staticmethod
    def validate_tick(tick: dict) -> bool:
        """
        Validate tick data has required fields and sane values.

        Required: symbol (str), bid (float > 0), ask (float > 0), timestamp.
        """
        if not isinstance(tick, dict):
            logger.warning("Tick is not a dict")
            return False

        missing = _REQUIRED_TICK_FIELDS - tick.keys()
        if missing:
            logger.warning(f"Tick missing fields: {missing}")
            return False

        symbol = tick.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            logger.warning("Tick has invalid symbol")
            return False

        try:
            bid = float(tick["bid"])
            ask = float(tick["ask"])
        except (TypeError, ValueError):
            logger.warning("Tick bid/ask not numeric")
            return False

        if bid <= 0 or ask <= 0:
            logger.warning(f"Tick bid/ask non-positive: bid={bid}, ask={ask}")
            return False

        if ask < bid:
            logger.warning(f"Tick ask < bid: ask={ask}, bid={bid}")
            return False

        return True

    @staticmethod
    def validate_candle(candle: dict) -> bool:
        """
        Validate candle data has required fields and OHLC invariants.

        Invariants: high >= max(open, close), low <= min(open, close).
        """
        if not isinstance(candle, dict):
            logger.warning("Candle is not a dict")
            return False

        missing = _REQUIRED_CANDLE_FIELDS - candle.keys()
        if missing:
            logger.warning(f"Candle missing fields: {missing}")
            return False

        try:
            o = float(candle["open"])
            h = float(candle["high"])
            l_ = float(candle["low"])
            c = float(candle["close"])
        except (TypeError, ValueError):
            logger.warning("Candle OHLC not numeric")
            return False

        if any(v <= 0 for v in (o, h, l_, c)):
            logger.warning("Candle OHLC contains non-positive value")
            return False

        if h < max(o, c) or l_ > min(o, c):
            logger.warning(
                f"Candle OHLC invariant violated: O={o} H={h} L={l_} C={c}"
            )
            return False

        return True
