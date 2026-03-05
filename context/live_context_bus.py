"""LiveContextBus - in-process context store for candles and ticks.

This module is analysis-only; it stores market context used by the pipeline.
No execution logic, no side effects beyond internal state.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from config.pip_values import get_pip_multiplier

# Maximum candle history entries per symbol:timeframe key.
# Prevents unbounded memory growth during long-running sessions.
CANDLE_MAX_BUFFER = 250


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
        # {symbol: conditioned return list}
        self._conditioned_returns: dict[str, list[float]] = {}
        # {symbol: diagnostics dict}
        self._conditioning_meta: dict[str, dict[str, Any]] = {}

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
        """Append a single candle to the history for its symbol/timeframe.

        Enforces ``CANDLE_MAX_BUFFER`` per key to prevent unbounded memory growth.
        When the limit is reached the oldest candles are dropped.
        """
        symbol = candle.get("symbol", "")
        timeframe = candle.get("timeframe", "")
        if not symbol or not timeframe:
            return
        key = f"{symbol}:{timeframe}"
        if key not in self._candle_history:
            self._candle_history[key] = []
        buf = self._candle_history[key]
        buf.append(candle)
        if len(buf) > CANDLE_MAX_BUFFER:
            self._candle_history[key] = buf[-CANDLE_MAX_BUFFER:]

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
        self._conditioned_returns = {}
        self._conditioning_meta = {}

    def update_conditioned_returns(
        self,
        symbol: str,
        returns: list[float],
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        """Store latest conditioned return series and optional diagnostics."""
        if not symbol:
            return
        self._conditioned_returns[symbol] = [float(r) for r in returns]
        if diagnostics is not None:
            self._conditioning_meta[symbol] = dict(diagnostics)

    def get_conditioned_returns(
        self,
        symbol: str,
        count: int | None = None,
    ) -> list[float]:
        """Return latest conditioned return series for a symbol."""
        data = self._conditioned_returns.get(symbol, [])
        if count is not None and count < len(data):
            return data[-count:]
        return list(data)

    def get_conditioning_meta(self, symbol: str) -> dict[str, Any] | None:
        """Return latest signal-conditioning diagnostics for a symbol."""
        meta = self._conditioning_meta.get(symbol)
        return dict(meta) if meta is not None else None

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

    def check_price_drift(
        self,
        symbol: str,
        max_drift_pips: float,
    ) -> dict[str, Any]:
        """Compare latest REST H1 close with WS mid-price to detect drift.

        Args:
            symbol:         Trading symbol (e.g. ``EURUSD``).
            max_drift_pips: Maximum acceptable drift in pips.

        Returns:
            Stable dict consumed by ``H1RefreshScheduler``::

                {
                    "drifted":    bool,
                    "drift_pips": float,
                    "rest_close": float | None,
                    "ws_mid":     float | None,
                }
        """
        # Latest REST H1 bar close
        h1_candles = self.get_candles(symbol, "H1")
        rest_close: float | None = h1_candles[-1]["close"] if h1_candles else None

        # Latest WS tick mid-price
        tick = self.get_latest_tick(symbol)
        ws_mid: float | None = None
        if tick:
            bid = tick.get("bid") or tick.get("price")
            ask = tick.get("ask") or tick.get("price")
            if bid is not None and ask is not None:
                ws_mid = (float(bid) + float(ask)) / 2.0
            elif bid is not None:
                ws_mid = float(bid)

        # Cannot compute drift without both prices
        if rest_close is None or ws_mid is None:
            return {
                "drifted": False,
                "drift_pips": 0.0,
                "rest_close": rest_close,
                "ws_mid": ws_mid,
            }

        # Convert raw price difference to pips
        try:
            multiplier = get_pip_multiplier(symbol)
        except LookupError:
            # Fall back to standard forex multiplier
            multiplier = 10_000.0

        drift_pips = abs(rest_close - ws_mid) * multiplier
        drifted = drift_pips > max_drift_pips

        if drifted:
            logger.warning(
                "Price drift alert: %s REST_close=%.5f WS_mid=%.5f "
                "drift=%.1f pips (max=%.1f)",
                symbol,
                rest_close,
                ws_mid,
                drift_pips,
                max_drift_pips,
            )

        return {
            "drifted": drifted,
            "drift_pips": drift_pips,
            "rest_close": rest_close,
            "ws_mid": ws_mid,
        }

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
    ) -> list[dict[str, Any]]:
        """Return stored candle history for *symbol*/*timeframe*.

        Args:
            symbol:    Trading symbol.
            timeframe: Timeframe string (e.g. "H1").
            count:     If given, return only the last *count* candles.

        Returns:
            List of candle dicts (empty list if no data stored).
        """
        key = f"{symbol}:{timeframe}"
        data = self._candle_history.get(key, [])
        if count is not None and count < len(data):
            return data[-count:]
        return data
