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

from dashboard.price_feed import PriceFeed
from dashboard.trade_ledger import TradeLedger
from journal.journal_router import JournalRouter
from schemas.trade_models import CloseReason, TradeStatus

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
        self._journal = JournalRouter()

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

        raise AttributeError("TradeLedger does not expose a supported status update method")

    async def _process_trade(self, trade: Any) -> None:
        """Process a single trade against the current price."""
        pair: str = trade.pair
        direction: str = trade.direction
        status = trade.status
        trade_id: str = trade.trade_id

        # Get first leg entry/sl/tp
        legs = getattr(trade, "legs", [])
        if not legs:
            return
        leg = legs[0]
        entry: float = leg.entry
        sl: float = leg.sl
        tp: float = leg.tp

        # Fetch live price
        price_data = self._price_feed.get_price(pair)
        if not price_data:
            return

        bid: float = float(price_data.get("bid", 0.0))
        ask: float = float(price_data.get("ask", 0.0))

        # Validate price data
        if bid <= 0.0 or ask <= 0.0:
            return

        if status == TradeStatus.PENDING:
            # BUY: entry hit when ask price reaches entry level
            if direction == "BUY" and ask <= entry:
                logger.info("PENDING->OPEN: BUY %s entry hit at ask=%.5f", trade_id, ask)
                self._update_trade_status(trade_id, TradeStatus.OPEN)
            # SELL: entry hit when bid price reaches entry level
            elif direction == "SELL" and bid >= entry:
                logger.info("PENDING->OPEN: SELL %s entry hit at bid=%.5f", trade_id, bid)
                self._update_trade_status(trade_id, TradeStatus.OPEN)

        elif status == TradeStatus.OPEN:
            if direction == "BUY":
                if bid >= tp:
                    logger.info("OPEN->CLOSED: BUY %s TP hit at bid=%.5f", trade_id, bid)
                    self._update_trade_status(
                        trade_id,
                        TradeStatus.CLOSED,
                        close_reason=CloseReason.TP_HIT,
                        pnl=None,
                    )
                elif bid <= sl:
                    logger.info("OPEN->CLOSED: BUY %s SL hit at bid=%.5f", trade_id, bid)
                    self._update_trade_status(
                        trade_id,
                        TradeStatus.CLOSED,
                        close_reason=CloseReason.SL_HIT,
                        pnl=None,
                    )
            elif direction == "SELL":
                if ask <= tp:
                    logger.info("OPEN->CLOSED: SELL %s TP hit at ask=%.5f", trade_id, ask)
                    self._update_trade_status(
                        trade_id,
                        TradeStatus.CLOSED,
                        close_reason=CloseReason.TP_HIT,
                        pnl=None,
                    )
                elif ask >= sl:
                    logger.info("OPEN->CLOSED: SELL %s SL hit at ask=%.5f", trade_id, ask)
                    self._update_trade_status(
                        trade_id,
                        TradeStatus.CLOSED,
                        close_reason=CloseReason.SL_HIT,
                        pnl=None,
                    )
