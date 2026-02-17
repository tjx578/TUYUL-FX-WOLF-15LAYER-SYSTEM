"""
Live Context Bus
Single Source of Truth for live market state.

Supports two modes via CONTEXT_MODE environment variable:
  - local (default): In-memory storage, single-process only
  - redis: Redis-backed storage for multi-container deployments
"""

from __future__ import annotations

import itertools
import os
import time
from collections import defaultdict, deque
from threading import Lock
from typing import TYPE_CHECKING

from loguru import logger  # pyright: ignore[reportMissingImports]

from config.constants import get_threshold
from context.context_validator import ContextValidator
from utils.timezone_utils import now_utc

if TYPE_CHECKING:
    from context.redis_context_bridge import RedisContextBridge

# Get candle history maxlen from config
CANDLE_HISTORY_MAXLEN: int = get_threshold("pipeline.candle_history_maxlen", 250)


class LiveContextBus:
    """
    Centralized, thread-safe market state container.

    Supports two modes:
      - CONTEXT_MODE=local (default): In-memory only, for local dev/testing
      - CONTEXT_MODE=redis: Writes to Redis for multi-container setups
    """

    _instance: LiveContextBus | None = None
    _lock = Lock()

    def __new__(cls) -> LiveContextBus:
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        """Initialize context bus based on CONTEXT_MODE."""
        # Always maintain local storage for backward compatibility
        self._tick_buffer = deque(maxlen=10000)
        self._candle_store = defaultdict(dict)  # symbol -> tf -> candle
        self._candle_history = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=CANDLE_HISTORY_MAXLEN))
        )  # symbol -> tf -> deque of candles
        self._news_store = {}
        self._meta = {}
        self._rw_lock = Lock()
        self._last_tick_ts: dict[str, float] = {}  # symbol -> Unix timestamp of last tick
        self._macro_state: dict = {}

        # Check mode and initialize Redis bridge if needed
        self._mode = os.getenv("CONTEXT_MODE", "local").lower()
        self._redis_bridge: RedisContextBridge | None = None

        if self._mode == "redis":
            try:
                # Lazy import to avoid circular dependency
                from context.redis_context_bridge import RedisContextBridge  # noqa: PLC0415

                self._redis_bridge = RedisContextBridge()
                logger.info("LiveContextBus initialized in REDIS mode")
            except Exception as exc:
                logger.error(
                    f"Failed to initialize Redis bridge: {exc}. Falling back to local mode."
                )
                self._mode = "local"
                self._redis_bridge = None
        else:
            logger.info("LiveContextBus initialized in LOCAL mode")

        # Consumer cursor tracking (consumer_id -> last read index)
        self._consumer_cursors: dict[str, int] = {}
        self._tick_seq: int = 0  # monotonic sequence counter for tick buffer

    # =========================
    # WRITE METHODS (INGEST ONLY)
    # =========================

    def update_tick(self, tick: dict) -> None:
        """
        Update tick data.

        In local mode: Stores in in-memory buffer.
        In Redis mode: Stores locally AND writes to Redis.
        """
        if not ContextValidator.validate_tick(tick):
            logger.warning("Invalid tick rejected")
            return

        with self._rw_lock:
            self._tick_buffer.append(tick)
            self._tick_seq += 1
            # Update last tick timestamp
            self._last_tick_ts[tick["symbol"]] = time.time()

        # If Redis mode, also write to Redis
        if self._mode == "redis" and self._redis_bridge:
            try:
                self._redis_bridge.write_tick(tick)
            except Exception as exc:
                logger.error(f"Failed to write tick to Redis: {exc}")

    def update_candle(self, candle: dict) -> None:
        """
        Update candle data.

        In local mode: Stores in in-memory store.
        In Redis mode: Stores locally AND writes to Redis.
        """
        if not ContextValidator.validate_candle(candle):
            logger.warning("Invalid candle rejected")
            return

        symbol = candle["symbol"]
        tf = candle["timeframe"]

        with self._rw_lock:
            self._candle_store[symbol][tf] = candle
            # Also add to history buffer
            self._candle_history[symbol][tf].append(candle)

        # If Redis mode, also write to Redis
        if self._mode == "redis" and self._redis_bridge:
            try:
                self._redis_bridge.write_candle(candle)
            except Exception as exc:
                logger.error(f"Failed to write candle to Redis: {exc}")

    def update_news(self, news: dict) -> None:
        """
        Update news data.

        In local mode: Stores in in-memory store.
        In Redis mode: Stores locally AND writes to Redis.
        """
        if not ContextValidator.validate_news(news): # pyright: ignore[reportAttributeAccessIssue]
            logger.warning("Invalid news payload rejected")
            return

        with self._rw_lock:
            self._news_store = news
            self._meta["news_updated_at"] = now_utc()

        # If Redis mode, also write to Redis
        if self._mode == "redis" and self._redis_bridge:
            try:
                self._redis_bridge.write_news(news)
            except Exception as exc:
                logger.error(f"Failed to write news to Redis: {exc}")

    def update_macro_state(self, state: dict) -> None:
        """
        Update macro volatility state from MacroVolatilityEngine.

        Args:
            state: Macro state dict with vix_level, vix_regime, multipliers, etc.
        """
        with self._rw_lock:
            self._macro_state = state
            self._meta["macro_updated_at"] = now_utc()

        logger.debug(f"Macro state updated: {state.get('vix_regime', 'UNKNOWN')}")

    # =========================
    # READ METHODS (EVERYONE ELSE)
    # =========================

    def consume_ticks(self, consumer_id: str = "candle_builder") -> list[dict]:
        """
        Non-destructive tick consumption with per-consumer cursors.

        Each consumer tracks its own read position. Ticks remain in the
        buffer for other consumers. Buffer is bounded by deque maxlen.

        Args:
            consumer_id: Unique identifier for the consumer.

        Returns:
            List of ticks not yet seen by this consumer.
        """
        with self._rw_lock:
            buf = self._tick_buffer
            buf_len = len(buf)
            cursor = self._consumer_cursors.get(consumer_id, 0)

            # If deque has wrapped (maxlen overflow), reset cursor
            if cursor > self._tick_seq:
                cursor = max(0, self._tick_seq - buf_len)

            # Calculate how many ticks back from _tick_seq the cursor is
            start_offset = self._tick_seq - cursor
            if start_offset > buf_len:
                start_offset = buf_len
            if start_offset <= 0:
                self._consumer_cursors[consumer_id] = self._tick_seq
                return []

            # Slice from the right end of the deque without full materialisation
            result = list(itertools.islice(buf, buf_len - start_offset, buf_len))
            self._consumer_cursors[consumer_id] = self._tick_seq
            return result

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

    def get_candle_history(self, symbol: str, timeframe: str, count: int = 20) -> list:
        """
        Get historical candles for a symbol and timeframe.

        Args:
            symbol: Trading pair symbol
            timeframe: Timeframe (M15, H1, etc.)
            count: Number of candles to return (default 20, max 50)

        Returns:
            List of candles, newest first
        """
        with self._rw_lock:
            history = self._candle_history.get(symbol, {}).get(timeframe, deque())
            # Return last N candles, newest first
            candles = list(history)
            return candles[-count:] if len(candles) > count else candles

    def get_news(self):
        with self._rw_lock:
            return self._news_store

    def get_macro_state(self) -> dict:
        """Get current macro volatility state."""
        with self._rw_lock:
            return self._macro_state.copy()

    def snapshot(self):
        """
        Read-only snapshot for analysis / dashboard.
        """
        with self._rw_lock:
            return {
                "ticks": list(self._tick_buffer),
                "candles": dict(self._candle_store),
                "news": self._news_store,
                "macro": self._macro_state,
                "meta": self._meta,
            }

    def get_feed_age(self, symbol: str) -> float | None:
        """
        Get seconds since last tick for a symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            Seconds since last tick, or None if no tick received
        """
        with self._rw_lock:
            last_ts = self._last_tick_ts.get(symbol)
            if last_ts is None:
                return None
            return time.time() - last_ts

    def is_feed_stale(self, symbol: str, threshold_sec: float = 30.0) -> bool:
        """
        Check if feed for a symbol is stale.

        Args:
            symbol: Trading pair symbol
            threshold_sec: Staleness threshold in seconds (default 30.0)

        Returns:
            True if feed is stale or no data, False otherwise
        """
        age = self.get_feed_age(symbol)
        if age is None:
            return True
        return age > threshold_sec

    def get_feed_status(self, symbol: str) -> str:
        """
        Get feed status for a symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            Feed status: "CONNECTED", "DEGRADED", "DOWN", or "NO_DATA"
        """
        age = self.get_feed_age(symbol)
        if age is None:
            return "NO_DATA"
        if age <= 10.0:
            return "CONNECTED"
        if age <= 30.0:
            return "DEGRADED"
        return "DOWN"

    def get_warmup_bar_count(self, symbol: str, timeframe: str) -> int:
        """
        Count candles in history for warmup validation.

        Args:
            symbol: Trading pair symbol
            timeframe: Timeframe (M15, H1, H4, D1, W1)

        Returns:
            Number of candles in history for this symbol/timeframe
        """
        with self._rw_lock:
            history = self._candle_history.get(symbol, {}).get(timeframe, deque())
            return len(history)

    def check_warmup(
        self,
        symbol: str,
        min_bars: dict[str, int] | None = None,
    ) -> dict:
        """Check if a symbol has sufficient candle history for analysis.

        Args:
            symbol: Trading pair symbol.
            min_bars: Minimum bars per timeframe.
                Defaults to ``{"M15": 20, "H1": 20, "H4": 10, "D1": 5}``.

        Returns:
            ``{"ready": bool, "bars": {tf: count}, "required": {tf: min},
              "missing": {tf: shortfall}}``
        """
        if min_bars is None:
            min_bars = {"M15": 20, "H1": 20, "H4": 10, "D1": 5}

        bars: dict[str, int] = {}
        missing: dict[str, int] = {}
        ready = True

        with self._rw_lock:
            for tf, required in min_bars.items():
                count = len(
                    self._candle_history.get(symbol, {}).get(tf, deque())
                )
                bars[tf] = count
                if count < required:
                    ready = False
                    missing[tf] = required - count

        return {
            "ready": ready,
            "bars": bars,
            "required": dict(min_bars),
            "missing": missing,
        }

    def check_price_drift(self, symbol: str, max_drift_pips: float = 50.0) -> dict:
        """
        Compare REST H1 close vs WS mid price for integrity check.

        Args:
            symbol: Trading pair symbol
            max_drift_pips: Maximum allowed drift in pips (default 50.0)

        Returns:
            Dict with keys: drifted (bool), drift_pips (float),
            rest_close (float), ws_mid (float)
        """
        with self._rw_lock:
            # Get latest H1 candle close
            h1_candle = self._candle_store.get(symbol, {}).get("H1")
            if not h1_candle:
                return {
                    "drifted": False,
                    "drift_pips": 0.0,
                    "rest_close": None,
                    "ws_mid": None,
                    "reason": "No H1 candle",
                }

            rest_close = h1_candle["close"]

            # Get latest tick mid price
            latest_tick = None
            for tick in reversed(self._tick_buffer):
                if tick["symbol"] == symbol:
                    latest_tick = tick
                    break

            if not latest_tick:
                return {
                    "drifted": False,
                    "drift_pips": 0.0,
                    "rest_close": rest_close,
                    "ws_mid": None,
                    "reason": "No WS tick",
                }

            # Calculate mid price
            bid = latest_tick.get("bid")
            ask = latest_tick.get("ask")

            if bid is None or ask is None:
                ws_mid = bid or ask or latest_tick.get("last", rest_close)
            else:
                ws_mid = (bid + ask) / 2.0

            # Calculate drift in pips
            # Assume 5-digit for forex, 2-digit for gold, 3-digit for silver
            if "XAU" in symbol:
                pip_multiplier = 100.0  # 2 digits
            elif "XAG" in symbol:
                pip_multiplier = 1000.0  # 3 digits
            else:
                pip_multiplier = 10000.0  # 5 digits (forex)

            drift_pips = abs(rest_close - ws_mid) * pip_multiplier
            drifted = drift_pips > max_drift_pips

            return {
                "drifted": drifted,
                "drift_pips": drift_pips,
                "rest_close": rest_close,
                "ws_mid": ws_mid,
            }

    def get_data_completeness(self, symbol: str) -> dict:
        """
        Return per-TF bar count for a symbol.

        Used by system_state validation.

        Args:
            symbol: Trading pair symbol

        Returns:
            Dict with keys: W1, D1, H4, H1, M15 (bar counts)
        """
        with self._rw_lock:
            return {
                "W1": len(self._candle_history.get(symbol, {}).get("W1", deque())),
                "D1": len(self._candle_history.get(symbol, {}).get("D1", deque())),
                "H4": len(self._candle_history.get(symbol, {}).get("H4", deque())),
                "H1": len(self._candle_history.get(symbol, {}).get("H1", deque())),
                "M15": len(self._candle_history.get(symbol, {}).get("M15", deque())),
            }

    def get_last_tick_time(self, symbol: str) -> float | None:
        """
        Get Unix timestamp of most recent tick for a symbol.
        Used by VaultHealthChecker for feed freshness monitoring.

        Uses the in-process ``_last_tick_ts`` dict which is populated by
        ``push_tick`` — works in both local and redis modes.
        """
        with self._rw_lock:
            return self._last_tick_ts.get(symbol)

    def update_last_tick_time(self, symbol: str, timestamp: float) -> None:
        """Called by ingest when a new tick arrives."""
        with self._rw_lock:
            self._last_tick_ts[symbol] = timestamp

    # =========================================================
    # ACCOUNT STATE — live account data for L6 risk evaluation
    # =========================================================
    #
    # Write: dashboard / EA pushes via update_account_state().
    # Read:  pipeline reads via get_account_state().
    #
    # If no external writer has pushed state, get_account_state()
    # pulls from RiskManager singleton as fallback — so the bus
    # always returns *something* even if dashboard is not running.
    # =========================================================

    def update_account_state(self, state: dict) -> None:
        """Push live account state into the bus.

        Called by dashboard backend or EA interface whenever account
        metrics change (equity tick, trade open/close, daily reset).

        Expected keys (all optional, merge semantics):
            equity          (float)  current equity
            peak_equity     (float)  high-water mark
            balance         (float)  cash balance
            daily_loss_pct  (float)  0-1 fraction lost today
            open_positions  (int)    number of open trades
            max_open_positions (int) configured max
            consecutive_losses (int) running streak
            circuit_breaker_active (bool)
            corr_exposure   (float)  cross-pair correlation load
            base_kelly      (float)  Kelly fraction estimate
        """
        with self._rw_lock:
            if not hasattr(self, "_account_state"):
                self._account_state: dict = {}
            self._account_state.update(state)
            self._meta["account_updated_at"] = now_utc()

        logger.debug("Account state updated via bus: %s", list(state.keys()))

    def get_account_state(self, symbol: str | None = None) -> dict:
        """Return the best-available account state for L6 consumption.

        Resolution order:
          1. Cached state pushed by dashboard (update_account_state).
          2. RiskManager singleton snapshot (live risk governor).
          3. Empty dict — L6 applies safe defaults.

        The *symbol* parameter is accepted for future per-symbol
        partitioning but currently ignored (single-account model).

        Returns
        -------
        dict
            Account state with keys matching L6RiskAnalyzer.analyze()
            ``account_state`` parameter.
        """
        # 1. Check bus cache first
        with self._rw_lock:
            cached = getattr(self, "_account_state", None)
            if cached:
                return dict(cached)  # shallow copy under lock

        # 2. Fallback: pull from RiskManager singleton
        try:
            from risk.risk_manager import RiskManager  # noqa: PLC0415

            rm = RiskManager.get_instance()
            snap = rm.get_risk_snapshot()

            balance = float(snap.get("balance", 0.0))
            daily_loss_raw = float(snap.get("daily_loss", 0.0))
            circuit = bool(snap.get("circuit_open", False))
            max_open = int(snap.get("max_open_trades", 5))

            daily_loss_pct = (
                abs(daily_loss_raw) / balance
                if balance > 0 and daily_loss_raw < 0
                else 0.0
            )

            return {
                "equity": balance,          # RiskManager tracks balance
                "peak_equity": balance,     # best-effort from RM
                "balance": balance,
                "daily_loss_pct": daily_loss_pct,
                "circuit_breaker_active": circuit,
                "max_open_positions": max_open,
            }
        except Exception as exc:
            logger.debug(
                "RiskManager unavailable for account state fallback: %s", exc,
            )

        # 3. Empty — L6 will use safe defaults
        return {}

    # =========================================================
    # TRADE HISTORY — per-trade P&L for L6/L7 risk evaluation
    # =========================================================

    def get_trade_history(
        self,
        symbol: str | None = None,
        lookback: int = 200,
    ) -> list[float]:
        """Return historical per-trade P&L for L6/L7 consumption.

        Resolution order:
          1. trade_archive (Redis → PostgreSQL → ledger cache).
          2. Empty list — L6/L7 degrade gracefully.

        Parameters
        ----------
        symbol : str | None
            Filter by pair. ``None`` returns all symbols.
        lookback : int
            Maximum number of returns (default 200).

        Returns
        -------
        list[float]
            P&L values, most-recent first. Empty if unavailable.
        """
        try:
            from storage.trade_archive import get_closed_returns  # noqa: PLC0415

            returns = get_closed_returns(symbol=symbol, lookback=lookback)
            if returns:
                logger.debug(
                    "Trade history loaded via bus: %d returns (symbol=%s)",
                    len(returns), symbol,
                )
                return returns
        except Exception as exc:
            logger.debug("trade_archive unavailable via bus: %s", exc)

        return []
