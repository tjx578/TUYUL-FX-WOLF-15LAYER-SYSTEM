"""
L1 — Market Context Analysis
NO EXECUTION | NO DECISION
"""

from datetime import datetime

from context.live_context_bus import LiveContextBus
from analysis.market.volatility import VolatilityAnalyzer
from utils.timezone_utils import is_trading_session


class L1ContextAnalyzer:
    def __init__(self):
        self.context = LiveContextBus()
        self.volatility = VolatilityAnalyzer()

    def analyze(self, symbol: str) -> dict:
        h1 = self.context.get_candle(symbol, "H1")
        news = self.context.get_news()

        if not h1:
            return {"valid": False, "reason": "no_h1_candle"}

        context = {
            "session": is_trading_session(h1["timestamp"]),
            "news_lock": self._is_news_lock(news, symbol),
            "valid": True,
        }

        return context

    @staticmethod
    def _is_news_lock(news: dict, symbol: str) -> bool:
        if not news:
            return False
        # detail filtering dilakukan di news engine
        return False
