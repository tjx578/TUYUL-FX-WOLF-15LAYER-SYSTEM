"""Zone A: MicroCandleChain — tick → M15 aggregation (M1/M5 disabled).

Zone: ingest/ — data pipeline, no analysis side-effects.

Architecture
------------
Each symbol gets a single M15 CandleBuilder fed directly by ticks:
  tick → M15

On completion:
  • M15 closed → publish_candle_sync()  (writes wolf15:candle_history:{SYM}:M15)
      Required for engine warmup validation.  M1/M5 writes are disabled
      to eliminate ~90% of Redis pressure while keeping warmup functional.

The M15 builders are exposed via .m15_builders so FormingBarPublisher
can register them for the 500ms forming-bar preview writes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from core.candle_bridge_fix import publish_candle_sync
from ingest.candle_builder import Candle, CandleBuilder, Timeframe


class MicroCandleChain:
    """Per-symbol M1→M5→M15 tick aggregation chain.

    Zone A of the Dual-Zone SSOT Architecture v5.  Feeds the same tick
    stream that the existing M15→H1 chain receives, building shorter
    timeframes for TRQ micro-wave analysis.

    Usage::

        chain = MicroCandleChain(redis)
        chain.init_symbols(["EURUSD", "GBPUSD"])

        # In tick callback:
        chain.on_tick(symbol, price, ts, volume)

        # For FormingBarPublisher registration:
        for sym, builder in chain.m15_builders.items():
            forming_pub.register_builder(sym, "M15", builder)
    """

    def __init__(self, redis: Any) -> None:
        """Initialize with M15 builder only (M1/M5 disabled).

        Parameters
        ----------
        redis:
            Async Redis client for M15 candle writes (required for engine warmup).
        """
        self._redis = redis

        # Per-symbol M15 builders keyed by symbol
        self._m15_builders: dict[str, CandleBuilder] = {}

        # Completion counter (for observability)
        self._m15_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init_symbols(self, symbols: list[str]) -> None:
        """Create M15 builders for each symbol."""
        for sym in symbols:
            self._build_chain(sym)
        logger.info(
            "[MicroCandleChain] Zone A wired for %d symbols (M15 only)",
            len(symbols),
        )

    def on_tick(
        self,
        symbol: str,
        price: float,
        ts: datetime,
        volume: float = 0.0,
    ) -> None:
        """Feed a tick into the M15 builder for this symbol.

        Creates builders on first tick if init_symbols() was not called.
        """
        m15 = self._m15_builders.get(symbol)
        if m15 is None:
            self._build_chain(symbol)
            m15 = self._m15_builders[symbol]
        m15.on_tick(price, ts, volume)

    @property
    def m15_builders(self) -> dict[str, CandleBuilder]:
        """Read-only view of M15 builders for FormingBarPublisher registration."""
        return dict(self._m15_builders)

    def health(self) -> dict[str, Any]:
        """Return completion counts for monitoring."""
        return {
            "symbols": list(self._m15_builders.keys()),
            "m15_completed": self._m15_count,
        }

    # ------------------------------------------------------------------
    # Internal chain construction
    # ------------------------------------------------------------------

    def _build_chain(self, symbol: str) -> None:
        """Build M15 builder only - write M15 to Redis, no M1/M5."""
        redis = self._redis

        def _on_m15_complete(candle: Candle) -> None:
            self._m15_count += 1
            # WRITE M15 to Redis for engine warmup
            publish_candle_sync(candle.to_dict(), redis=redis)
            logger.debug(
                "[MicroCandleChain] M15 closed and written to Redis %s #%d",
                candle.symbol,
                self._m15_count,
            )

        m15_builder = CandleBuilder(
            symbol=symbol,
            timeframe=Timeframe.M15,
            on_complete=_on_m15_complete,
        )

        self._m15_builders[symbol] = m15_builder
