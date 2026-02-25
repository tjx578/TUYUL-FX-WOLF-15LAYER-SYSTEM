"""
Trade Ledger Service - In-memory + Redis-backed trade state store.

Provides:
  - create_trade: Create new trade with legs
  - update_status: Update trade status with transition validation
  - get_active_trades: Get all non-terminal trades
  - get_trade: Get single trade by ID
  - get_trades_by_account: Get all trades for an account

Valid state transitions:
  INTENDED -> PENDING (trader confirms order placed)
  INTENDED -> CANCELLED (system or trader cancels before placing)
  INTENDED -> SKIPPED (trader skips)
  PENDING -> OPEN (price watcher detects entry hit)
  PENDING -> CANCELLED (expiry, M15 invalid, news lock, DD breach)
  OPEN -> CLOSED (SL/TP hit or manual close)

Storage:
  - Redis: TRADE:{trade_id} with JSON serialization
  - Sorted set: TRADES:ACTIVE (sorted by created_at timestamp)
"""

import json
import os
from threading import Lock
from typing import Optional

from loguru import logger

from schemas.trade_models import (
    CloseReason,
    RiskMode,
    Trade,
    TradeLeg,
    TradeStatus,
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
        self._cache: dict[str, Trade] = {}
        self._rw_lock = Lock()
        self._trade_counter = 0

        self._load_from_redis()
        logger.info("TradeLedger initialized")

    def _load_from_redis(self) -> None:
        """Load all trades from Redis into cache."""
        try:
            pattern = f"{self._redis_prefix}:TRADE:*"
            client = self._redis.client
            loaded_count = 0

            for key in client.scan_iter(match=pattern, count=100):  # type: ignore[union-attr]
                trade_json = self._redis.get(key)
                if trade_json:
                    trade_data = json.loads(trade_json)
                    trade = Trade(**trade_data)
                    self._cache[trade.trade_id] = trade
                    loaded_count += 1

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
        legs: list[dict],
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
        now = now_utc()
        timestamp = int(now.timestamp() * 1000)
        self._trade_counter += 1
        trade_id = f"T-{timestamp}-{self._trade_counter}"

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

        trade = Trade(
            trade_id=trade_id,
            signal_id=signal_id,
            account_id=account_id,
            pair=pair,
            direction=direction,
            status=TradeStatus.INTENDED,
            risk_mode=RiskMode(risk_mode),
            total_risk_percent=total_risk_percent,
            total_risk_amount=total_risk_amount,
            legs=trade_legs,
            created_at=now,
            updated_at=now,
        )

        with self._rw_lock:
            self._cache[trade_id] = trade

            try:
                redis_key = f"{self._redis_prefix}:TRADE:{trade_id}"
                self._redis.set(redis_key, trade.model_dump_json())

                # Add to active trades sorted set — single call only
                active_key = f"{self._redis_prefix}:TRADES:ACTIVE"
                self._redis.client.zadd(active_key, {trade_id: now.timestamp()})

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
        close_reason: CloseReason | None = None,
        pnl: float | None = None,
    ) -> tuple[bool, str]:
        """
        Update trade status with transition validation.

        Returns:
            (success, code): code is 'OK', 'NOT_FOUND', 'INVALID_TRANSITION', 'REDIS_ERROR'
        """
        with self._rw_lock:
            trade = self._cache.get(trade_id)

            if not trade:
                logger.warning(f"Trade not found: {trade_id}")
                return False, "NOT_FOUND"

            if not is_valid_transition(trade.status, new_status):
                logger.warning(
                    f"Invalid transition: {trade.status} -> {new_status} for {trade_id}"
                )
                return False, "INVALID_TRANSITION"

            old_status = trade.status
            trade.status = new_status
            trade.updated_at = now_utc()

            if new_status == TradeStatus.CLOSED:
                if close_reason:
                    trade.close_reason = close_reason
                if pnl is not None:
                    trade.pnl = pnl

            for leg in trade.legs:
                leg.status = new_status

            self._cache[trade_id] = trade

            logger.info(
                f"Updated trade {trade_id}: {old_status} -> {new_status}"
                + (f" | Reason: {close_reason}" if close_reason else "")
                + (f" | P&L: ${pnl:.2f}" if pnl is not None else "")
            )

            try:
                redis_key = f"{self._redis_prefix}:TRADE:{trade_id}"
                self._redis.set(redis_key, trade.model_dump_json())

                if new_status in (TradeStatus.CLOSED, TradeStatus.CANCELLED, TradeStatus.SKIPPED):
                    active_key = f"{self._redis_prefix}:TRADES:ACTIVE"
                    self._redis.client.zrem(active_key, trade_id)

            except Exception as exc:
                logger.error(f"Failed to update trade in Redis: {exc}")
                return False, "REDIS_ERROR"

            return True, "OK"

    def get_trade(self, trade_id: str) -> Trade | None:
        """
        Get trade by ID.

        Args:
            trade_id: Trade ID

        Returns:
            Trade instance if found, else None
        """
        if trade_id in self._cache:
            return self._cache[trade_id]

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

    def get_active_trades(self) -> list[Trade]:
        """
        Get all active trades (not CLOSED/CANCELLED/SKIPPED).

        Returns:
            List of active Trade instances
        """
        with self._rw_lock:
            return [
                trade
                for trade in self._cache.values()
                if trade.status
                not in (TradeStatus.CLOSED, TradeStatus.CANCELLED, TradeStatus.SKIPPED)
            ]

    def get_trades_by_account(self, account_id: str) -> list[Trade]:
        """
        Get all trades for an account.

        Args:
            account_id: Account ID

        Returns:
            List of Trade instances for the account
        """
        with self._rw_lock:
            return [
                trade for trade in self._cache.values()
                if trade.account_id == account_id
            ]

    def get_trade_count(self) -> int:
        """Get total number of trades."""
        with self._rw_lock:
            return len(self._cache)


# Singleton instance for imports
trade_ledger = TradeLedger()
