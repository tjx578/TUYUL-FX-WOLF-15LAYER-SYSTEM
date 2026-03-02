"""LiveContextBus - in-process context store for candles and ticks.

This module is analysis-only; it stores market context used by the pipeline.
No execution logic, no side effects beyond internal state.
"""

from __future__ import annotations

from typing import Any

from loguru import logger


class LiveContextBus:
    """Central in-memory bus for live market context (candles, ticks, etc.)."""

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
        self._candle_history: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Write API (analysis / consumer only — no execution logic)
    # ------------------------------------------------------------------

    def set_candle_history(
        self,
        symbol: str,
        timeframe: str,
        candles: list[dict[str, Any]],
    ) -> None:
        """Replace candle history for *symbol*/*timeframe*."""
        key = f"{symbol}:{timeframe}"
        self._candle_history[key] = candles

    def push_candle(self, candle: dict[str, Any]) -> None:
        """Append a single candle to the history for its symbol/timeframe."""
        symbol = candle.get("symbol", "")
        timeframe = candle.get("timeframe", "")
        if not symbol or not timeframe:
            return
        key = f"{symbol}:{timeframe}"
        if key not in self._candle_history:
            self._candle_history[key] = []
        self._candle_history[key].append(candle)

    def update_candle(self, candle: dict[str, Any]) -> None:
        """Backward-compatible wrapper for pushing a candle.

        Candle must contain 'symbol' and 'timeframe'.
        """
        symbol = str(candle.get("symbol", "")).strip()
        timeframe = str(candle.get("timeframe", "")).strip()
        if not symbol or not timeframe:
            logger.warning(
                "LiveContextBus.update_candle: candle missing symbol/timeframe — ignored"
            )
            return
        self.push_candle(candle)

    def update_tick(self, tick: dict[str, Any]) -> None:
        """Store latest tick for a symbol. Tick must contain 'symbol' key."""
        symbol = tick.get("symbol")
        if symbol:
            self._ticks[str(symbol)] = tick
        else:
            logger.warning(
                "LiveContextBus.update_tick: tick missing 'symbol' key — ignored"
            )

    def reset_state(self) -> None:
        """Clear all internal candle history. Used for test isolation."""
        self._candle_history: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get_candles(self, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        """Return stored candles for symbol/timeframe (empty list if none).

        Reads from the unified ``_candle_history`` store that is populated by
        ``set_candle_history``, ``push_candle``, and ``update_candle``.
        """
        key = f"{symbol}:{timeframe}"
        return self._candle_history.get(key, [])

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
            min_bars: Mapping of timeframe -> required minimum bar count.
                      Example: {"H4": 200, "H1": 500, "M15": 1000}

        Returns:
            Stable schema consumed by pipeline + tests::

                {
                    "ready":    bool,
                    "bars":     {tf: have_int, ...},       # all tfs
                    "required": {tf: need_int, ...},       # all tfs
                    "missing":  {tf: shortfall_int, ...},  # only tfs that are short
                    "details":  {tf: {"have": int, "need": int, "missing": int}, ...},
                }

            ``bars``, ``required``, and ``missing`` are always present (may be
            empty dicts if ``min_bars`` is empty).  ``details`` mirrors the
            per-tf breakdown and is kept for backward-compat with consumers that
            already access ``result["details"]``.
        """
        bars: dict[str, int] = {}
        required_map: dict[str, int] = {}
        missing: dict[str, int] = {}
        details: dict[str, dict[str, int]] = {}

        ready = True

        for timeframe, required in min_bars.items():
            tf = str(timeframe)
            need = int(required)
            have = int(self.get_warmup_bar_count(symbol, tf))

            bars[tf] = have
            required_map[tf] = need

            shortfall = max(0, need - have)
            details[tf] = {"have": have, "need": need, "missing": shortfall}

            if shortfall > 0:
                ready = False
                missing[tf] = shortfall
                logger.debug(
                    "LiveContextBus: warmup not ready for %s:%s"
                    " — have %d, need %d (missing %d)",
                    symbol,
                    tf,
                    have,
                    need,
                    shortfall,
                )

        return {
            "ready": ready,
            "bars": bars,
            "required": required_map,
            "missing": missing,
            "details": details,
        }

    def get_candle_history(
        self, symbol: str, timeframe: str, count: int | None = None
    ) -> list[dict[str, Any]] | None:
        """Return stored candle history for *symbol*/*timeframe*, or None if absent.

        Args:
            symbol:    Trading symbol.
            timeframe: Timeframe string (e.g. "H1").
            count:     If given, return only the last *count* candles.
        """
        key = f"{symbol}:{timeframe}"
        data = self._candle_history.get(key)
        if data is None:
            return None
        if count is not None and count < len(data):
            return data[-count:]
        return data
