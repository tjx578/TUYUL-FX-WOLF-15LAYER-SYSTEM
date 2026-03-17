"""LiveContextBus — ephemeral inference state machine.

NOT storage.  TUYUL thinks with state abstractions, not raw data.

Two layers:
  1. **Data layer** — candles, ticks, conditioned returns.
     Raw market observations with overflow protection.
  2. **Inference layer** — regime_state, volatility_regime, session_state,
     liquidity_map, news_pressure_vector, signal_stack.
     Derived abstract state that analysis layers produce and L12 consumes.

This module is analysis-only; no execution logic, no side effects beyond
internal state.  The inference layer is what makes the system stable —
it reasons over abstractions, not noisy raw feeds.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any

from loguru import logger

from config.pip_values import get_pip_multiplier

# Maximum candle history entries per symbol:timeframe key.
# Prevents unbounded memory growth during long-running sessions.
CANDLE_MAX_BUFFER = 250


class LiveContextBus:
    """Ephemeral inference state machine for live market context.

    Singleton.  Two semantic layers:
    - **data**: raw candles / ticks / conditioned returns.
    - **inference**: abstract regime, session, liquidity, news pressure,
      and signal-stack state produced by analysis layers.

    All inference fields are ephemeral: they reflect the *current* system
    belief and are overwritten on every refresh cycle.  No persistence
    beyond in-process memory.
    """

    _instance: LiveContextBus | None = None

    @classmethod
    def reset_singleton(cls) -> None:
        """Reset the singleton instance (for testing only)."""
        cls._instance = None

    def __new__(cls) -> LiveContextBus:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    # ------------------------------------------------------------------
    # Internal init (called once)
    # ------------------------------------------------------------------

    def _init(self) -> None:
        self._lock = Lock()

        # ── Data layer (raw market observations) ──────────────────────
        # {symbol: {timeframe: [candle_dict, ...]}}
        self._candles: dict[str, dict[str, list[dict[str, Any]]]] = {}
        # {symbol: tick_dict}
        self._ticks: dict[str, dict[str, Any]] = {}
        self._candle_history: dict[str, list[dict[str, Any]]] = {}
        # {symbol: conditioned return list}
        self._conditioned_returns: dict[str, list[float]] = {}
        # {symbol: diagnostics dict}
        self._conditioning_meta: dict[str, dict[str, Any]] = {}

        # ── Inference layer (abstract state — what TUYUL thinks with) ─
        self._regime_state: dict[str, Any] = {}  # macro regime (0/1/2 + vix fields)
        self._volatility_regime: str = "NORMAL"  # LOW / NORMAL / HIGH / EXTREME
        self._session_state: dict[str, Any] = {}  # session window + multiplier
        self._liquidity_map: dict[str, Any] = {}  # SMC zone abstractions
        self._news_pressure_vector: dict[str, Any] = {}  # impact-weighted sentiment
        self._news: dict[str, Any] = {}  # raw news events
        self._signal_stack: list[dict[str, Any]] = []  # pending signal candidates
        self._inference_ts: float = 0.0  # last inference update epoch

        # ── Account / trade layer ─────────────────────────────────────
        self._account_state: dict[str, dict[str, Any]] = {}  # {symbol: account_snapshot}
        self._trade_history: dict[str, list[float]] = {}  # {symbol: [return_pct, ...]}

        # ── Feed staleness tracking ────────────────────────────────────
        # Records wall-clock time of the most recent tick per symbol.
        self._feed_timestamps: dict[str, float] = {}  # {symbol: epoch_sec}

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
            logger.warning("LiveContextBus.update_candle: candle missing symbol/timeframe — ignored")
            return
        self.push_candle(candle)

    def update_tick(self, tick: dict[str, Any]) -> None:
        """Store latest tick for a symbol. Tick must contain 'symbol' key."""
        symbol = tick.get("symbol")
        if symbol:
            sym = str(symbol)
            with self._lock:
                self._ticks[sym] = tick
                self._feed_timestamps[sym] = time.time()
        else:
            logger.warning("LiveContextBus.update_tick: tick missing 'symbol' key — ignored")

    def reset_state(self) -> None:
        """Clear all internal state. Used for test isolation."""
        with self._lock:
            # Data layer
            self._candles = {}
            self._ticks = {}
            self._candle_history = {}
            self._conditioned_returns = {}
            self._conditioning_meta = {}
            # Inference layer
            self._regime_state = {}
            self._volatility_regime = "NORMAL"
            self._session_state = {}
            self._liquidity_map = {}
            self._news_pressure_vector = {}
            self._news = {}
            self._signal_stack = []
            self._inference_ts = 0.0
            # Feed staleness tracking
            self._feed_timestamps = {}

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
    # Inference layer — write API
    # These methods update the abstract state TUYUL reasons with.
    # Each write is atomic (lock-protected) and timestamped.
    # ------------------------------------------------------------------

    def update_macro_state(self, state: dict[str, Any]) -> None:
        """Update macro regime state (from MacroVolatilityEngine).

        Expected fields: vix_level, vix_regime, regime_state (0/1/2),
        volatility_multiplier, risk_multiplier, source, timestamp.
        """
        with self._lock:
            self._regime_state = dict(state)
            # Derive volatility_regime label from regime_state int
            rs = state.get("regime_state", 1)
            fallback_regime = str(state.get("vix_regime") or "NORMAL")
            if rs == 0:
                self._volatility_regime = "LOW"
            elif rs == 1:
                self._volatility_regime = "NORMAL"
            elif rs == 2:
                self._volatility_regime = "HIGH"
            else:
                self._volatility_regime = fallback_regime
            self._inference_ts = time.time()

    def update_news(self, news: dict[str, Any]) -> None:
        """Update news events payload.

        Expected shape: {"events": [...], "source": str}.
        """
        with self._lock:
            self._news = dict(news)
            self._inference_ts = time.time()

    def update_session_state(self, state: dict[str, Any]) -> None:
        """Update session window state (from L1 context analyzer).

        Expected fields: session (e.g. "LONDON_OPEN"), session_multiplier,
        is_overlap, major_session_active.
        """
        with self._lock:
            self._session_state = dict(state)
            self._inference_ts = time.time()

    def update_liquidity_map(self, liq: dict[str, Any]) -> None:
        """Update liquidity zone abstractions (from L9 SMC).

        Expected fields: zones list, nearest_zone, zone_strength.
        """
        with self._lock:
            self._liquidity_map = dict(liq)
            self._inference_ts = time.time()

    def update_news_pressure(self, pressure: dict[str, Any]) -> None:
        """Update news pressure vector (from NewsEngine).

        Expected fields: pressure_score, locked_symbols, high_impact_pending.
        """
        with self._lock:
            self._news_pressure_vector = dict(pressure)
            self._inference_ts = time.time()

    def push_signal(self, signal: dict[str, Any]) -> None:
        """Push a signal candidate onto the stack.

        Keeps last 50 signals max (ephemeral — not a journal).
        """
        with self._lock:
            self._signal_stack.append(dict(signal))
            if len(self._signal_stack) > 50:
                self._signal_stack = self._signal_stack[-50:]
            self._inference_ts = time.time()

    def clear_signal_stack(self) -> None:
        """Clear the signal stack (e.g. after cycle completion)."""
        with self._lock:
            self._signal_stack = []

    # ------------------------------------------------------------------
    # Inference layer — read API
    # All reads return copies to prevent mutation of internal state.
    # ------------------------------------------------------------------

    def get_macro_state(self) -> dict[str, Any]:
        """Return current macro regime state (copy)."""
        with self._lock:
            return dict(self._regime_state)

    def get_news(self) -> dict[str, Any] | None:
        """Return current news events or None if empty."""
        with self._lock:
            return dict(self._news) if self._news else None

    def get_session_state(self) -> dict[str, Any]:
        """Return current session window state (copy)."""
        with self._lock:
            return dict(self._session_state)

    def get_volatility_regime(self) -> str:
        """Return current volatility regime label."""
        with self._lock:
            return self._volatility_regime

    def get_liquidity_map(self) -> dict[str, Any]:
        """Return current liquidity zone map (copy)."""
        with self._lock:
            return dict(self._liquidity_map)

    def get_news_pressure(self) -> dict[str, Any]:
        """Return current news pressure vector (copy)."""
        with self._lock:
            return dict(self._news_pressure_vector)

    def get_signal_stack(self) -> list[dict[str, Any]]:
        """Return current signal candidate stack (copy)."""
        with self._lock:
            return [dict(s) for s in self._signal_stack]

    def inference_snapshot(self) -> dict[str, Any]:
        """Return unified inference state — what TUYUL thinks with.

        This is the abstract state the system reasons over.
        Not raw data, but derived beliefs.
        """
        with self._lock:
            return {
                "regime_state": dict(self._regime_state),
                "volatility_regime": self._volatility_regime,
                "session_state": dict(self._session_state),
                "liquidity_map": dict(self._liquidity_map),
                "news_pressure_vector": dict(self._news_pressure_vector),
                "signal_stack": [dict(s) for s in self._signal_stack],
                "inference_ts": self._inference_ts,
            }

    # ------------------------------------------------------------------
    # Convenience: single candle read (latest bar for symbol/tf)
    # ------------------------------------------------------------------

    def get_candle(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        """Return the latest candle for symbol/timeframe, or None."""
        key = f"{symbol}:{timeframe}"
        buf = self._candle_history.get(key, [])
        return dict(buf[-1]) if buf else None

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow-immutable view of the live context state.

        Includes both data layer and inference layer.
        Intended for read-only API consumers and diagnostics.
        """
        with self._lock:
            return {
                # Data layer
                "candles": {key: [dict(c) for c in candles] for key, candles in self._candle_history.items()},
                "ticks": {symbol: dict(tick) for symbol, tick in self._ticks.items()},
                "conditioned_returns": {symbol: list(values) for symbol, values in self._conditioned_returns.items()},
                "conditioning_meta": {symbol: dict(meta) for symbol, meta in self._conditioning_meta.items()},
                # Inference layer
                "macro": dict(self._regime_state),
                "news": dict(self._news) if self._news else {},
                "inference": {
                    "regime_state": dict(self._regime_state),
                    "volatility_regime": self._volatility_regime,
                    "session_state": dict(self._session_state),
                    "liquidity_map": dict(self._liquidity_map),
                    "news_pressure_vector": dict(self._news_pressure_vector),
                    "signal_stack": [dict(s) for s in self._signal_stack],
                    "inference_ts": self._inference_ts,
                },
                "meta": {
                    "inference_ts": self._inference_ts,
                    "volatility_regime": self._volatility_regime,
                },
            }

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

    # ------------------------------------------------------------------
    # Feed staleness API (read-only — no execution logic)
    # ------------------------------------------------------------------

    def get_feed_age(self, symbol: str) -> float | None:
        """Return seconds since the last tick for *symbol*, or None if no tick received."""
        ts = self._feed_timestamps.get(symbol)
        if ts is None:
            return None
        return time.time() - ts

    def is_feed_stale(self, symbol: str, threshold_sec: float = 30.0) -> bool:
        """Return True if the feed for *symbol* has not updated within *threshold_sec* seconds."""
        age = self.get_feed_age(symbol)
        if age is None:
            return True
        return age > threshold_sec

    def get_feed_status(self, symbol: str) -> str:
        """Return a human-readable feed status for *symbol*.

        Returns:
            "CONNECTED"  — tick received within the last 30 seconds.
            "DEGRADED"   — tick received within the last 120 seconds.
            "DOWN"       — tick received but older than 120 seconds.
            "NO_DATA"    — no tick ever received for this symbol.
        """
        age = self.get_feed_age(symbol)
        if age is None:
            return "NO_DATA"
        if age <= 30.0:
            return "CONNECTED"
        if age <= 120.0:
            return "DEGRADED"
        return "DOWN"

    def check_price_drift(
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
                "Price drift alert: %s REST_close=%.5f WS_mid=%.5f drift=%.1f pips (max=%.1f)",
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
                    "LiveContextBus: warmup not ready for %s:%s — have %d, need %d (missing %d)",
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

    def get_candle_history(self, symbol: str, timeframe: str, count: int | None = None) -> list[dict[str, Any]]:
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

    # ------------------------------------------------------------------
    # Account / trade history
    # ------------------------------------------------------------------

    def update_account_state(self, symbol: str, state: dict[str, Any]) -> None:
        """Store the latest account-state snapshot for *symbol*."""
        with self._lock:
            self._account_state[symbol] = state

    def get_account_state(self, symbol: str) -> dict[str, Any]:
        """Return stored account-state snapshot (empty dict if none)."""
        with self._lock:
            return dict(self._account_state.get(symbol, {}))

    def update_trade_history(self, symbol: str, returns: list[float]) -> None:
        """Replace the stored trade-return series for *symbol*."""
        with self._lock:
            self._trade_history[symbol] = list(returns)

    def get_trade_history(self, symbol: str, lookback: int | None = None) -> list[float] | None:
        """Return stored trade returns for *symbol*.

        Args:
            symbol:   Trading symbol.
            lookback: If given, return only the last *lookback* values.

        Returns:
            List of return floats, or ``None`` if no data stored.
        """
        with self._lock:
            data = self._trade_history.get(symbol)
            if data is None:
                return None
            if lookback is not None and lookback < len(data):
                return data[-lookback:]
            return list(data)
