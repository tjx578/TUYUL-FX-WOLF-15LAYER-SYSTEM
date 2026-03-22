"""Zone A: MicroCandleChain — tick → M1 → M5 → M15 aggregation chain.

Zone: ingest/ — data pipeline, no analysis side-effects.

Architecture
------------
Each symbol gets three chained CandleBuilders:
  tick → M1 → M5 → M15

On completion:
  • M1 closed  → publish_candle_sync()  (writes wolf15:candle_history:{SYM}:M1)
  • M5 closed  → publish_candle_sync()  (writes wolf15:candle_history:{SYM}:M5)
  • M15 closed → COUNT ONLY, NO Redis write.
      The existing M15→H1 chain in ingest_service.py already calls
      publish_candle_sync() for M15.  Writing again from here would
      create DUPLICATE entries in wolf15:candle_history:{SYM}:M15,
      corrupting TRQ-3D R3D calculations.

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
        """
        Parameters
        ----------
        redis:
            Async Redis client passed to publish_candle_sync() for M1/M5 writes.
        """
        self._redis = redis

        # Per-symbol builders keyed by symbol
        self._m1_builders: dict[str, CandleBuilder] = {}
        self._m5_builders: dict[str, CandleBuilder] = {}
        self._m15_builders: dict[str, CandleBuilder] = {}

        # Completion counters (for observability / dedup guard)
        self._m1_count: int = 0
        self._m5_count: int = 0
        self._m15_count: int = 0  # M15 closes tracked but NOT written to Redis

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init_symbols(self, symbols: list[str]) -> None:
        """Create chained M1→M5→M15 builders for each symbol."""
        for sym in symbols:
            self._build_chain(sym)
        logger.info(
            "[MicroCandleChain] Zone A wired for %d symbols (M1→M5→M15)",
            len(symbols),
        )

    def on_tick(
        self,
        symbol: str,
        price: float,
        ts: datetime,
        volume: float = 0.0,
    ) -> None:
        """Feed a tick into the M1 builder for this symbol.

        Creates builders on first tick if init_symbols() was not called.
        """
        m1 = self._m1_builders.get(symbol)
        if m1 is None:
            self._build_chain(symbol)
            m1 = self._m1_builders[symbol]
        m1.on_tick(price, ts, volume)

    @property
    def m15_builders(self) -> dict[str, CandleBuilder]:
        """Read-only view of M15 builders for FormingBarPublisher registration."""
        return dict(self._m15_builders)

    def health(self) -> dict[str, Any]:
        """Return completion counts for monitoring."""
        return {
            "symbols": list(self._m1_builders.keys()),
            "m1_completed": self._m1_count,
            "m5_completed": self._m5_count,
            "m15_closed_counted": self._m15_count,
        }

    # ------------------------------------------------------------------
    # Internal chain construction
    # ------------------------------------------------------------------

    def _build_chain(self, symbol: str) -> None:
        """Build and wire the M1→M5→M15 chain for *symbol*."""
        redis = self._redis

        # M15: count only — NO Redis write (existing M15→H1 chain handles writes)
        def _on_m15_complete(candle: Candle) -> None:
            self._m15_count += 1
            logger.debug(
                "[MicroCandleChain] M15 closed (counted, not written) %s #%d",
                candle.symbol,
                self._m15_count,
            )

        # M5: publish to Redis and feed M15 builder
        m15_builder = CandleBuilder(
            symbol=symbol,
            timeframe=Timeframe.M15,
            on_complete=_on_m15_complete,
        )

        def _on_m5_complete(candle: Candle) -> None:
            self._m5_count += 1
            publish_candle_sync(candle.to_dict(), redis=redis)
            m15_builder.on_candle(candle)

        # M1: publish to Redis and feed M5 builder
        m5_builder = CandleBuilder(
            symbol=symbol,
            timeframe=Timeframe.M5,
            on_complete=_on_m5_complete,
        )

        def _on_m1_complete(candle: Candle) -> None:
            self._m1_count += 1
            publish_candle_sync(candle.to_dict(), redis=redis)
            m5_builder.on_candle(candle)

        m1_builder = CandleBuilder(
            symbol=symbol,
            timeframe=Timeframe.M1,
            on_complete=_on_m1_complete,
        )

        self._m1_builders[symbol] = m1_builder
        self._m5_builders[symbol] = m5_builder
        self._m15_builders[symbol] = m15_builder
