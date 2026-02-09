"""
Context Validator
Ensures all data entering LiveContextBus is structurally valid.
NO TRADING LOGIC.
"""

from typing import Dict

from context.context_keys import CANDLE, NEWS, TICK


class ContextValidator:
    @staticmethod
    def validate_tick(tick: Dict) -> bool:
        required = TICK.values()
        for key in required:
            if key not in tick:
                return False

        if not isinstance(tick[TICK["symbol"]], str):
            return False

        if tick[TICK["bid"]] is None or tick[TICK["ask"]] is None:
            return False

        return True

    @staticmethod
    def validate_candle(candle: Dict) -> bool:
        required = CANDLE.values()
        for key in required:
            if key not in candle:
                return False

        if candle[CANDLE["open"]] > candle[CANDLE["high"]]:
            return False
        if candle[CANDLE["low"]] > candle[CANDLE["high"]]:
            return False

        return True

    @staticmethod
    def validate_news(news: Dict) -> bool:
        if NEWS["events"] not in news:
            return False
        if not isinstance(news[NEWS["events"]], list):
            return False

        return True
# Placeholder
