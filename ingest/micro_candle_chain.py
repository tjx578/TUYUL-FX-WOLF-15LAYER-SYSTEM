"""Zone A: MicroCandleChain — tick → M15 aggregation (M1/M5 disabled).

Zone: ingest/ — data pipeline, no analysis side-effects.

Architecture
------------
Each symbol gets a single M15 CandleBuilder fed directly from ticks.
M1 and M5 builders have been removed to eliminate Redis connection pool
exhaustion caused by 90+ publish_candle_sync() calls per minute.

On completion:
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

from ingest.candle_builder import Candle, CandleBuilder, Timeframe


class MicroCandleChain:
    """Per-symbol M15 tick aggregation (M1/M5 disabled).

    Zone A of the Dual-Zone SSOT Architecture v5.  Feeds the same tick
    stream that the existing M15→H1 chain receives, building M15 candles
    for FormingBarPublisher without any Redis writes.

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
            Kept for interface compatibility; no Redis writes are made
            from this component.
        """
        self._redis = redis  # Keep for interface compatibility

        self._m15_builders: dict[str, CandleBuilder] = {}
        self._m15_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init_symbols(self, symbols: list[str]) -> None:
        """Create M15 builders for each symbol."""
        for sym in symbols:
            self._build_chain(sym)
        logger.info(
            "[MicroCandleChain] Zone A wired for %d symbols (M15 only - M1/M5 disabled)",
            len(symbols),
        )

    def on_tick(
        self,
        symbol: str,
        price: float,
        ts: datetime,
        volume: float = 0.0,
    ) -> None:
        """Feed tick directly to M15 builder.

        Creates builder on first tick if init_symbols() was not called.
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
        """Return M15 completion count."""
        return {
            "symbols": list(self._m15_builders.keys()),
            "m15_closed_counted": self._m15_count,
        }

    # ------------------------------------------------------------------
    # Internal chain construction
    # ------------------------------------------------------------------

    def _build_chain(self, symbol: str) -> None:
        """Build M15 builder only - no M1/M5, no Redis writes."""

        def _on_m15_complete(candle: Candle) -> None:
            self._m15_count += 1
            logger.debug(
                "[MicroCandleChain] M15 closed (counted only, no Redis write) %s #%d",
                candle.symbol,
                self._m15_count,
            )

        m15_builder = CandleBuilder(
            symbol=symbol,
            timeframe=Timeframe.M15,
            on_complete=_on_m15_complete,
        )

        self._m15_builders[symbol] = m15_builder
