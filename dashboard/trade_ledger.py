"""
Trade Ledger Service — In-memory + Redis-backed trade state store.

Provides:
  - create_trade: Create new trade with legs
  - update_status: Update trade status with transition validation
  - get_active_trades: Get all non-terminal trades
  - get_trade: Get single trade by ID
  - get_trades_by_account: Get all trades for an account

Valid state transitions:
  INTENDED → PENDING (trader confirms order placed)
  INTENDED → CANCELLED (system or trader cancels before placing)
  INTENDED → SKIPPED (trader skips)
  PENDING → OPEN (price watcher detects entry hit)
  PENDING → CANCELLED (expiry, M15 invalid, news lock, DD breach)
  OPEN → CLOSED (SL/TP hit or manual close)

Storage:
  - Redis: TRADE:{trade_id} with JSON serialization
  - Sorted set: TRADES:ACTIVE (sorted by created_at timestamp)
"""

import json
import os
from threading import Lock
from typing import Dict, List, Optional

from loguru import logger

from schemas.trade_models import (
    Trade,
    TradeLeg,
    TradeStatus,
    CloseReason,
    is_valid_transition,
)
from storage.redis_client import RedisClient
from utils.timezone_utils import now_utc


class TradeLedger:
    """
    Thread-safe trade ledger service.

    Manages trade lifecycle from INTENDED to terminal state.
    Enforces state transition rules and persists to Redis.
    """

    _instance: Optional["TradeLedger"] = None
    _lock = Lock()

    def __new__(cls) -> "TradeLedger":
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        """Initialize trade ledger."""
        self._redis = RedisClient()
        self._redis_prefix = os.getenv("REDIS_PREFIX", "wolf15")
        self._cache: Dict[str, Trade] = {}
        self._rw_lock = Lock()
        self._trade_counter = 0

        # Load existing trades from Redis on startup
        self._load_from_redis()

        logger.info("TradeLedger initialized")

    def _load_from_redis(self) -> None:
        """Load all trades from Redis into cache."""
        try:
            pattern = f"{self._redis_prefix}:TRADE:*"
            client = self._redis.client

            cursor = 0
            loaded_count = 0

            while True:
                cursor, keys = client.scan(cursor, match=pattern, count=100)

                for key in keys:
                    trade_json = self._redis.get(key)
                    if trade_json:
                        trade_data = json.loads(trade_json)
                        # Parse datetime fields
                        trade = Trade(**trade_data)
                        self._cache[trade.trade_id] = trade
                        loaded_count += 1

                if cursor == 0:
                    break

            if loaded_count > 0:
                logger.info(f"Loaded {loaded_count} trades from Redis")

        except Exception as exc:
            logger.error(f"Failed to load trades from Redis: {exc}")

    def create_trade(
        self,
        signal_id: str,
        account_id: str,
        pair: str,
        direction: str,
        risk_mode: str,
        total_risk_percent: float,
        total_risk_amount: float,
        legs: List[Dict],
    ) -> Trade:
        """
        Create a new trade in INTENDED status.

        Args:
            signal_id: Source signal ID
            account_id: Account ID
            pair: Trading pair
            direction: BUY or SELL
            risk_mode: FIXED or SPLIT
            total_risk_percent: Total risk %
            total_risk_amount: Total risk amount
            legs: List of leg dictionaries with entry, sl, tp, lot

        Returns:
            Created Trade instance
        """
        # Generate trade ID
        timestamp = int(now_utc().timestamp() * 1000)
        self._trade_counter += 1
        trade_id = f"T-{timestamp}-{self._trade_counter}"

        # Create trade legs
        trade_legs = [
            TradeLeg(
                leg=i + 1,
                entry=leg["entry"],
                sl=leg["sl"],
                tp=leg["tp"],
                lot=leg["lot"],
                status=TradeStatus.INTENDED,
            )
            for i, leg in enumerate(legs)
        ]

        # Create trade
        now = now_utc()
        trade = Trade(
            trade_id=trade_id,
            signal_id=signal_id,
            account_id=account_id,
            pair=pair,
            direction=direction,
            status=TradeStatus.INTENDED,
            risk_mode=risk_mode,
            total_risk_percent=total_risk_percent,
            total_risk_amount=total_risk_amount,
            legs=trade_legs,
            created_at=now,
            updated_at=now,
        )

        # Store in cache and Redis
        with self._rw_lock:
            self._cache[trade_id] = trade

            try:
                # Store trade
                redis_key = f"{self._redis_prefix}:TRADE:{trade_id}"
                self._redis.set(redis_key, trade.model_dump_json())

                # Add to active trades sorted set
                active_key = f"{self._redis_prefix}:TRADES:ACTIVE"
                self._redis.client.zadd(
                    active_key,
                    {trade_id: now.timestamp()}
                )

                logger.info(
                    f"Created trade: {trade_id} | {pair} {direction} | "
                    f"Risk: {total_risk_percent:.1f}% (${total_risk_amount:.2f})"
                )
            except Exception as exc:
                logger.error(f"Failed to save trade to Redis: {exc}")

        return trade

    def update_status(
        self,
        trade_id: str,
        new_status: TradeStatus,
        close_reason: Optional[CloseReason] = None,
        pnl: Optional[float] = None,
    ) -> bool:
        """
        Update trade status with transition validation.

        Args:
            trade_id: Trade ID
            new_status: New status
            close_reason: Reason for closure (required if new_status is CLOSED)
            pnl: P&L amount (for CLOSED status)

        Returns:
            True if updated successfully, False otherwise
        """
        with self._rw_lock:
            # Check cache first (avoid calling get_trade which may access Redis)
            trade = self._cache.get(trade_id)

            if not trade:
                logger.warning(f"Trade not found: {trade_id}")
                return False

            # Validate transition
            if not is_valid_transition(trade.status, new_status):
                logger.warning(
                    f"Invalid transition: {trade.status} → {new_status} for {trade_id}"
                )
                return False

            # Update status
            old_status = trade.status
            trade.status = new_status
            trade.updated_at = now_utc()

            # Update close reason and P&L if closing
            if new_status == TradeStatus.CLOSED:
                if close_reason:
                    trade.close_reason = close_reason
                if pnl is not None:
                    trade.pnl = pnl

            # Update leg statuses
            for leg in trade.legs:
                leg.status = new_status

            # Save to cache and Redis
            self._cache[trade_id] = trade

            # Log the update
            logger.info(
                f"Updated trade {trade_id}: {old_status} → {new_status}"
                + (f" | Reason: {close_reason}" if close_reason else "")
                + (f" | P&L: ${pnl:.2f}" if pnl is not None else "")
            )

            # Try to save to Redis (best effort - failure doesn't mean the update failed)
            try:
                redis_key = f"{self._redis_prefix}:TRADE:{trade_id}"
                self._redis.set(redis_key, trade.model_dump_json())

                # Remove from active trades if terminal state
                if new_status in (TradeStatus.CLOSED, TradeStatus.CANCELLED, TradeStatus.SKIPPED):
                    active_key = f"{self._redis_prefix}:TRADES:ACTIVE"
                    self._redis.client.zrem(active_key, trade_id)

            except Exception as exc:
                logger.error(f"Failed to update trade in Redis: {exc}")
                # Don't return False - cache update succeeded

            return True

    def get_trade(self, trade_id: str) -> Optional[Trade]:
        """
        Get trade by ID.

        Args:
            trade_id: Trade ID

        Returns:
            Trade instance if found, else None
        """
        # Check cache first
        if trade_id in self._cache:
            return self._cache[trade_id]

        # Try Redis
        try:
            redis_key = f"{self._redis_prefix}:TRADE:{trade_id}"
            trade_json = self._redis.get(redis_key)

            if trade_json:
                trade_data = json.loads(trade_json)
                trade = Trade(**trade_data)
                self._cache[trade_id] = trade
                return trade

        except Exception as exc:
            logger.error(f"Failed to get trade from Redis: {exc}")

        return None

    def get_active_trades(self) -> List[Trade]:
        """
        Get all active trades (not CLOSED/CANCELLED/SKIPPED).

        Returns:
            List of active Trade instances
        """
        with self._rw_lock:
            return [
                trade
                for trade in self._cache.values()
                if trade.status not in (TradeStatus.CLOSED, TradeStatus.CANCELLED, TradeStatus.SKIPPED)
            ]

    def get_trades_by_account(self, account_id: str) -> List[Trade]:
        """
        Get all trades for an account.

        Args:
            account_id: Account ID

        Returns:
            List of Trade instances for the account
        """
        with self._rw_lock:
            return [
                trade
                for trade in self._cache.values()
                if trade.account_id == account_id
            ]

    def get_trade_count(self) -> int:
        """
        Get total number of trades.

        Returns:
            Number of trades
        """
        with self._rw_lock:
            return len(self._cache)


# Singleton instance for imports
trade_ledger = TradeLedger()
