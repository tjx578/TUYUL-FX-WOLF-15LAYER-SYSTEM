"""LiveContextBus — in-process bus for candle/context data.

Zones: analysis (context sharing). No execution side-effects.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class LiveContextBus:
    """Singleton in-process bus that holds live candle context."""

    _instance: LiveContextBus | None = None

    def __new__(cls) -> LiveContextBus:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    # ------------------------------------------------------------------
    # Internal init (called once)
    # ------------------------------------------------------------------

    def _init(self) -> None:
        # {symbol: {timeframe: [candle_dict, ...]}}
        self._candles: dict[str, dict[str, list[dict[str, Any]]]] = {}
        # {symbol: tick_dict}
        self._ticks: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Write API (analysis / consumer only — no execution logic)
    # ------------------------------------------------------------------

    def set_candle_history(
        self,
        symbol: str,
        timeframe: str,
        candles: list[dict[str, Any]],
    ) -> None:
        """Replace stored candles for a symbol/timeframe (idempotent)."""
        self._candles.setdefault(symbol, {})[timeframe] = list(candles)

    def push_candle(self, symbol: str, timeframe: str, candle: dict[str, Any]) -> None:
        """Append a single live candle (from pub/sub)."""
        self._candles.setdefault(symbol, {}).setdefault(timeframe, []).append(candle)

    def update_tick(self, tick: dict[str, Any]) -> None:
        """Store latest tick for a symbol. Tick must contain 'symbol' key."""
        symbol = tick.get("symbol")
        if symbol:
            self._ticks[symbol] = tick
        else:
            logger.warning("LiveContextBus.update_tick: tick missing 'symbol' key — ignored")

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get_candles(
        self, symbol: str, timeframe: str
    ) -> list[dict[str, Any]]:
        """Return stored candles for symbol/timeframe (empty list if none)."""
        return self._candles.get(symbol, {}).get(timeframe, [])

    def get_latest_tick(self, symbol: str) -> dict[str, Any] | None:
        """Return latest tick for symbol, or None if not yet received."""
        return self._ticks.get(symbol)

    def get_warmup_bar_count(self, symbol: str, timeframe: str) -> int:
        """Return number of bars currently stored for symbol/timeframe."""
        return len(self.get_candles(symbol, timeframe))

    def check_warmup(
        self,
        symbol: str,
        min_bars: dict[str, int],
    ) -> dict[str, Any]:
        """Check whether all required timeframes meet minimum bar counts.

        Args:
            symbol:   Trading symbol to check.
            min_bars: Mapping of timeframe → required minimum bar count.

        Returns:
            ``{"ready": bool, "details": {timeframe: {"have": int, "need": int}}}``
        """
        details: dict[str, dict[str, int]] = {}
        ready = True

        for timeframe, required in min_bars.items():
            have = self.get_warmup_bar_count(symbol, timeframe)
            details[timeframe] = {"have": have, "need": required}
            if have < required:
                ready = False
                logger.debug(
                    "LiveContextBus: warmup not ready for %s:%s — have %d, need %d",
                    symbol,
                    timeframe,
                    have,
                    required,
                )

        return {"ready": ready, "details": details}
