"""
Live Context Bus
Single Source of Truth for live market state.
"""

from collections import defaultdict, deque
from datetime import datetime
from threading import Lock

from loguru import logger

from context.context_validator import ContextValidator


class LiveContextBus:
    """
    Centralized, thread-safe market state container.
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._tick_buffer = deque(maxlen=10000)
        self._candle_store = defaultdict(dict)  # symbol -> tf -> candle
        self._news_store = {}
        self._meta = {}

        self._rw_lock = Lock()

    # =========================
    # WRITE METHODS (INGEST ONLY)
    # =========================

    def update_tick(self, tick: dict):
        if not ContextValidator.validate_tick(tick):
            logger.warning("Invalid tick rejected")
            return

        with self._rw_lock:
            self._tick_buffer.append(tick)

    def update_candle(self, candle: dict):
        if not ContextValidator.validate_candle(candle):
            logger.warning("Invalid candle rejected")
            return

        symbol = candle["symbol"]
        tf = candle["timeframe"]

        with self._rw_lock:
            self._candle_store[symbol][tf] = candle

    def update_news(self, news: dict):
        if not ContextValidator.validate_news(news):
            logger.warning("Invalid news payload rejected")
            return

        with self._rw_lock:
            self._news_store = news
            self._meta["news_updated_at"] = datetime.utcnow()

    # =========================
    # READ METHODS (EVERYONE ELSE)
    # =========================

    def consume_ticks(self):
        """
        Used by CandleBuilder ONLY.
        """
        with self._rw_lock:
            ticks = list(self._tick_buffer)
            self._tick_buffer.clear()
            return ticks

    def get_latest_tick(self, symbol: str):
        with self._rw_lock:
            for tick in reversed(self._tick_buffer):
                if tick["symbol"] == symbol:
                    return tick
        return None

    def get_candle(self, symbol: str, timeframe: str):
        with self._rw_lock:
            return self._candle_store.get(symbol, {}).get(timeframe)

    def get_all_candles(self, timeframe: str):
        with self._rw_lock:
            return {
                symbol: tf_map.get(timeframe)
                for symbol, tf_map in self._candle_store.items()
                if timeframe in tf_map
            }

    def get_news(self):
        with self._rw_lock:
            return self._news_store

    def snapshot(self):
        """
        Read-only snapshot for analysis / dashboard.
        """
        with self._rw_lock:
            return {
                "ticks": list(self._tick_buffer),
                "candles": dict(self._candle_store),
                "news": self._news_store,
                "meta": self._meta,
            }
