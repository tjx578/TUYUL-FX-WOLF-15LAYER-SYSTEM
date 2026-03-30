"""
dashboard/price_watcher.py — Price-triggered trade status watcher

Monitors active trades and transitions them based on current market prices:
  - PENDING -> OPEN when entry price is hit
  - OPEN -> CLOSED when TP or SL is hit

Authority: Dashboard-layer execution monitor. No market analysis decisions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

from schemas.trade_models import CloseReason, TradeStatus
from storage.price_feed import PriceFeed
from storage.trade_ledger import TradeLedger

logger = logging.getLogger(__name__)


class PriceWatcher:
    """Monitors live prices and triggers trade state transitions.

    Logic:
        PENDING BUY:   ask <= entry  ->  OPEN
        PENDING SELL:  bid >= entry  ->  OPEN
        OPEN BUY:      bid >= tp     ->  CLOSED (TP_HIT)
        OPEN BUY:      bid <= sl     ->  CLOSED (SL_HIT)
        OPEN SELL:     ask <= tp     ->  CLOSED (TP_HIT)
        OPEN SELL:     ask >= sl     ->  CLOSED (SL_HIT)
    """

    def __init__(self) -> None:
        super().__init__()
        self._ledger = TradeLedger()
        self._price_feed = PriceFeed()
        self._transitioned: set[str] = set()

    async def _check_trades(self) -> None:
        """Check all active trades against current prices and trigger transitions."""
        try:
            active_trades = self._ledger.get_active_trades()
        except Exception:
            logger.exception("Failed to fetch active trades")
            return

        for trade in active_trades:
            try:
                await self._process_trade(trade)
            except Exception:
                logger.exception("Error processing trade %s", getattr(trade, "trade_id", "?"))

    def _update_trade_status(
        self,
        trade_id: str,
        status: TradeStatus,
        *,
        close_reason: CloseReason | None = None,
        pnl: float | None = None,
    ) -> None:
        """Typed compatibility wrapper for ledger status updates."""
        guard_key = f"{trade_id}:{status.value}"
        if guard_key in self._transitioned:
            logger.debug("Idempotency guard: %s already transitioned", guard_key)
            return
        self._transitioned.add(guard_key)

        # Preferred API
        preferred_updater = getattr(self._ledger, "update_status", None)
        if callable(preferred_updater):
            updater: Callable[..., None] = cast(Callable[..., None], preferred_updater)
            updater(trade_id, status, close_reason=close_reason, pnl=pnl)
            return

        # Backward/alternate API
        legacy_updater = getattr(self._ledger, "update_trade_status", None)
        if callable(legacy_updater):
            updater: Callable[..., None] = cast(Callable[..., None], legacy_updater)
            updater(trade_id, status, close_reason=close_reason, pnl=pnl)
            return

        self._transitioned.discard(guard_key)
        raise AttributeError("TradeLedger does not expose a supported status update method")

    @staticmethod
    def _compute_pnl(legs: list[Any], direction: str, close_price: float) -> float:
        """Aggregate PnL across all legs: (close - entry) * lot per leg."""
        total = 0.0
        for leg in legs:
            diff = (close_price - leg.entry) if direction == "BUY" else (leg.entry - close_price)
            total += diff * leg.lot
        return round(total, 6)

    async def _process_trade(self, trade: Any) -> None:
        """Process a single trade against the current price."""
        pair: str = trade.pair
        direction: str = trade.direction
        status = trade.status
        trade_id: str = trade.trade_id

        legs = getattr(trade, "legs", [])
        if not legs:
            return

        # Primary entry from first leg (trigger for PENDING -> OPEN)
        entry: float = legs[0].entry
        # Multi-leg SL/TP boundaries
        sls = [leg.sl for leg in legs]
        tps = [leg.tp for leg in legs]

        # Fetch live price
        price_data = self._price_feed.get_price(pair)
        if not price_data:
            return

        bid: float = float(price_data.get("bid", 0.0))
        ask: float = float(price_data.get("ask", 0.0))

        if bid <= 0.0 or ask <= 0.0:
            return

        if status == TradeStatus.PENDING:
            if direction == "BUY" and ask <= entry:
                logger.info("PENDING->OPEN: BUY %s entry hit at ask=%.5f", trade_id, ask)
                self._update_trade_status(trade_id, TradeStatus.OPEN)
            elif direction == "SELL" and bid >= entry:
                logger.info("PENDING->OPEN: SELL %s entry hit at bid=%.5f", trade_id, bid)
                self._update_trade_status(trade_id, TradeStatus.OPEN)

        elif status == TradeStatus.OPEN:
            if direction == "BUY":
                if bid >= min(tps):
                    pnl = self._compute_pnl(legs, direction, bid)
                    logger.info("OPEN->CLOSED: BUY %s TP hit at bid=%.5f pnl=%.6f", trade_id, bid, pnl)
                    self._update_trade_status(
                        trade_id,
                        TradeStatus.CLOSED,
                        close_reason=CloseReason.TP_HIT,
                        pnl=pnl,
                    )
                elif bid <= max(sls):
                    pnl = self._compute_pnl(legs, direction, bid)
                    logger.info("OPEN->CLOSED: BUY %s SL hit at bid=%.5f pnl=%.6f", trade_id, bid, pnl)
                    self._update_trade_status(
                        trade_id,
                        TradeStatus.CLOSED,
                        close_reason=CloseReason.SL_HIT,
                        pnl=pnl,
                    )
            elif direction == "SELL":
                if ask <= max(tps):
                    pnl = self._compute_pnl(legs, direction, ask)
                    logger.info("OPEN->CLOSED: SELL %s TP hit at ask=%.5f pnl=%.6f", trade_id, ask, pnl)
                    self._update_trade_status(
                        trade_id,
                        TradeStatus.CLOSED,
                        close_reason=CloseReason.TP_HIT,
                        pnl=pnl,
                    )
                elif ask >= min(sls):
                    pnl = self._compute_pnl(legs, direction, ask)
                    logger.info("OPEN->CLOSED: SELL %s SL hit at ask=%.5f pnl=%.6f", trade_id, ask, pnl)
                    self._update_trade_status(
                        trade_id,
                        TradeStatus.CLOSED,
                        close_reason=CloseReason.SL_HIT,
                        pnl=pnl,
                    )
