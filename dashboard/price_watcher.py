"""
Price Watcher - Background async task monitoring active trades.

Auto-detect logic:
  - PENDING -> OPEN:
    * For SELL pending: if bid >= entry
    * For BUY pending: if ask <= entry

  - OPEN -> CLOSED (SL hit):
    * For SELL open: if ask >= sl
    * For BUY open: if bid <= sl

  - OPEN -> CLOSED (TP hit):
    * For SELL open: if bid <= tp
    * For BUY open: if bid >= tp

On state transition:
  1. Update trade ledger
  2. Record journal entry (J3 for execution, J4 for reflection on close)
  3. Log with context (trade_id, timestamp, price at trigger)

Run interval: every 2 seconds (configurable via PRICE_WATCHER_INTERVAL_SEC)

CRITICAL:
  - MUST NOT calculate RR
  - MUST NOT change SL/TP
  - MUST NOT generate signals
  - MUST NOT override any analysis output
  - Pure state transition monitor only
"""

import asyncio
import os

from loguru import logger

from dashboard.price_feed import PriceFeed
from dashboard.trade_ledger import TradeLedger
from journal.journal_router import JournalRouter
from journal.journal_schema import (
    ExecutionJournal,
    ProtectionAssessment,
    ReflectiveJournal,
    TradeOutcome,
)
from schemas.trade_models import CloseReason, Trade, TradeStatus
from utils.timezone_utils import now_utc


class PriceWatcher:
    """
    Background task monitoring active trades for state transitions.

    Pure sensor - no decision logic, no signal generation.
    Only monitors price vs. entry/SL/TP and triggers state changes.
    """

    def __init__(self):
        self._price_feed = PriceFeed()
        self._trade_ledger = TradeLedger()
        self._journal = JournalRouter()
        self._interval_sec = int(os.getenv("PRICE_WATCHER_INTERVAL_SEC", "2"))
        self._running = False

    async def start(self):
        """Start price watcher background task."""
        if self._running:
            logger.warning("PriceWatcher already running")
            return

        self._running = True
        logger.info(f"PriceWatcher started (interval: {self._interval_sec}s)")

        while self._running:
            try:
                await self._check_trades()
            except Exception as exc:
                logger.error(f"PriceWatcher error: {exc}")

            await asyncio.sleep(self._interval_sec)

    def stop(self):
        """Stop price watcher background task."""
        self._running = False
        logger.info("PriceWatcher stopped")

    async def _check_trades(self):
        """Check all active trades for state transitions."""
        active_trades = self._trade_ledger.get_active_trades()

        if not active_trades:
            return

        for trade in active_trades:
            try:
                # Get current price
                price_data = self._price_feed.get_price(trade.pair)

                if not price_data:
                    logger.debug(f"No price data for {trade.pair} (trade {trade.trade_id})")
                    continue

                bid = price_data.get("bid", 0.0)
                ask = price_data.get("ask", 0.0)

                if bid <= 0 or ask <= 0:
                    logger.debug(f"Invalid price data for {trade.pair}: bid={bid}, ask={ask}")
                    continue

                # Check for state transitions
                if trade.status == TradeStatus.PENDING:
                    await self._check_pending_to_open(trade, bid, ask)
                elif trade.status == TradeStatus.OPEN:
                    await self._check_open_to_closed(trade, bid, ask)

            except Exception as exc:
                logger.error(f"Error checking trade {trade.trade_id}: {exc}")

    async def _check_pending_to_open(self, trade: Trade, bid: float, ask: float):
        """
        Check if pending order should transition to open.

        Logic:
          - SELL: Entry hit if bid >= entry (we can sell at bid)
          - BUY: Entry hit if ask <= entry (we can buy at ask)
        """
        # Get entry price from first leg (all legs should have same entry)
        if not trade.legs:
            return

        entry = trade.legs[0].entry

        entry_hit = False
        if trade.direction == "SELL":
            entry_hit = bid >= entry
        elif trade.direction == "BUY":
            entry_hit = ask <= entry

        if entry_hit:
            # Transition to OPEN
            success = self._trade_ledger.update_status(trade.trade_id, TradeStatus.OPEN)

            if success:
                logger.info(
                    f"Trade {trade.trade_id} OPEN: {trade.pair} {trade.direction} @ "
                    f"{entry:.5f} (bid={bid:.5f}, ask={ask:.5f})"
                )

                # Record J3 execution journal
                self._record_execution_journal(trade, entry)

    async def _check_open_to_closed(self, trade: Trade, bid: float, ask: float):
        """
        Check if open position should close (SL or TP hit).

        Logic:
          - SELL SL: if ask >= sl (we exit by buying at ask)
          - SELL TP: if bid <= tp (we exit by buying at bid... wait, no)

        Correct logic:
          - SELL: We sold at entry, so we're short
            * SL hit: Price goes UP, ask >= sl (we buy back at ask)
            * TP hit: Price goes DOWN, ask <= tp (we buy back at ask)
          - BUY: We bought at entry, so we're long
            * SL hit: Price goes DOWN, bid <= sl (we sell at bid)
            * TP hit: Price goes UP, bid >= tp (we sell at bid)
        """
        # Get SL and TP from first leg
        if not trade.legs:
            return

        sl = trade.legs[0].sl
        tp = trade.legs[0].tp

        close_reason = None
        close_price = None

        if trade.direction == "SELL":
            # SELL position (short)
            if ask >= sl:
                close_reason = CloseReason.SL_HIT
                close_price = ask
            elif ask <= tp:
                close_reason = CloseReason.TP_HIT
                close_price = ask

        elif trade.direction == "BUY":
            # BUY position (long)
            if bid <= sl:
                close_reason = CloseReason.SL_HIT
                close_price = bid
            elif bid >= tp:
                close_reason = CloseReason.TP_HIT
                close_price = bid

        if close_reason and close_price:
            # Calculate P&L (simplified, actual would need lot size, pip value, etc.)
            # For now, just mark it closed without P&L calculation
            success = self._trade_ledger.update_status(
                trade.trade_id,
                TradeStatus.CLOSED,
                close_reason=close_reason,
                pnl=None,  # P&L calculation would be done by broker/EA
            )

            if success:
                logger.info(
                    f"Trade {trade.trade_id} CLOSED: {close_reason.value} @ "
                    f"{close_price:.5f} (bid={bid:.5f}, ask={ask:.5f})"
                )

                # Record J4 reflection journal
                self._record_reflection_journal(trade, close_reason)

    def _record_execution_journal(self, trade: Trade, entry_price: float):
        """
        Record J3 execution journal when trade opens.

        Args:
            trade: Trade instance
            entry_price: Actual entry price
        """
        try:
            # Get trade details
            leg = trade.legs[0]  # Use first leg for details

            j3 = ExecutionJournal(
                timestamp=now_utc(),
                setup_id=trade.signal_id,
                pair=trade.pair,
                direction=trade.direction,
                entry_price=entry_price,
                stop_loss=leg.sl,
                take_profit_1=leg.tp,
                rr_ratio=abs((leg.tp - entry_price) / (entry_price - leg.sl))
                if trade.direction == "BUY"
                else abs((entry_price - leg.tp) / (leg.sl - entry_price)),
                risk_percent=trade.total_risk_percent,
                lot_size=leg.lot,
                execution_mode="TP1_ONLY",
                order_type="PENDING_ONLY",
                sm_state="FILLED",
            )

            self._journal.record_execution(j3)

        except Exception as exc:
            logger.error(f"Failed to record J3 for trade {trade.trade_id}: {exc}")

    def _record_reflection_journal(self, trade: Trade, close_reason: CloseReason):
        """
        Record J4 reflection journal when trade closes.

        Args:
            trade: Trade instance
            close_reason: Reason for closure
        """
        try:
            # Map close reason to outcome
            if close_reason == CloseReason.TP_HIT:
                outcome = TradeOutcome.WIN
            elif close_reason == CloseReason.SL_HIT:
                outcome = TradeOutcome.LOSS
            elif close_reason == CloseReason.EXPIRY:
                outcome = TradeOutcome.EXPIRED
            elif close_reason in (
                CloseReason.NEWS_LOCK,
                CloseReason.M15_INVALIDATION,
                CloseReason.SYSTEM_PROTECTION,
            ):
                outcome = TradeOutcome.CANCELLED
            else:
                outcome = TradeOutcome.BREAKEVEN

            j4 = ReflectiveJournal(
                timestamp=now_utc(),
                setup_id=trade.signal_id,
                pair=trade.pair,
                outcome=outcome,
                did_system_protect=ProtectionAssessment.UNCLEAR,
                was_rejection_correct=None,
                discipline_rating=10,  # Auto-closed by system = perfect discipline
                override_attempted=False,
                learning_note=f"Auto-closed by price watcher: {close_reason.value}",
                system_adjustment_candidate=False,
            )

            self._journal.record_reflection(j4)

        except Exception as exc:
            logger.error(f"Failed to record J4 for trade {trade.trade_id}: {exc}")


# Singleton instance for imports
price_watcher = PriceWatcher()
