"""
Open Risk Tracker — Tracks aggregate open exposure per account.

Calculates: open_risk = Σ (lot × sl_distance_pips × pip_value)
Persisted in Redis. Updated on INTENDED/OPEN/CLOSE events.
"""

import json

from dataclasses import asdict, dataclass

from loguru import logger

from storage.redis_client import RedisClient


@dataclass
class OpenTrade:
    """Single open trade entry for risk tracking."""

    trade_id: str
    symbol: str
    lot_size: float
    sl_distance_pips: float
    pip_value: float
    risk_amount: float  # lot × sl_dist × pip_value
    entry_number: int = 1  # 1 or 2 for SPLIT mode


class OpenRiskTracker:
    """
    Redis-backed open risk and trade count tracker.

    Maintains a registry of INTENDED/PENDING/OPEN trades per account.
    Provides aggregate risk exposure and trade count for guards.
    """

    _KEY_PREFIX = "wolf15:risk:open_trades:"

    def __init__(self, account_id: str) -> None:
        self._account_id = account_id
        self._redis = RedisClient()
        self._key = f"{self._KEY_PREFIX}{account_id}"

    def _load_trades(self) -> list[dict]:
        raw = self._redis.get(self._key)
        if not raw:
            return []
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Corrupt open trades data, resetting", account_id=self._account_id)
            return []

    def _save_trades(self, trades: list[dict]) -> None:
        self._redis.set(self._key, json.dumps(trades))

    def add_trade(self, trade: OpenTrade) -> None:
        trades = self._load_trades()
        existing_ids = {(t["trade_id"], t.get("entry_number", 1)) for t in trades}
        key = (trade.trade_id, trade.entry_number)
        if key in existing_ids:
            logger.warning(
                "Trade already registered, skipping",
                trade_id=trade.trade_id,
                entry=trade.entry_number,
            )
            return
        trades.append(asdict(trade))
        self._save_trades(trades)
        logger.info(
            "Open trade registered",
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            risk_amount=trade.risk_amount,
            total_open=len(trades),
        )

    def remove_trade(self, trade_id: str, entry_number: int = 1) -> None:
        trades = self._load_trades()
        trades = [
            t
            for t in trades
            if not (t["trade_id"] == trade_id and t.get("entry_number", 1) == entry_number)
        ]
        self._save_trades(trades)
        logger.info(
            "Open trade removed", trade_id=trade_id, entry=entry_number, remaining=len(trades)
        )

    def get_open_risk(self) -> float:
        trades = self._load_trades()
        return sum(t.get("risk_amount", 0.0) for t in trades)

    def get_open_count(self) -> int:
        trades = self._load_trades()
        unique_ids = {t["trade_id"] for t in trades}
        return len(unique_ids)

    def get_snapshot(self) -> dict:
        trades = self._load_trades()
        unique_ids = {t["trade_id"] for t in trades}
        return {
            "open_risk_amount": sum(t.get("risk_amount", 0.0) for t in trades),
            "open_trade_count": len(unique_ids),
            "open_entry_count": len(trades),
            "trades": trades,
        }

    def clear(self) -> None:
        self._redis.delete(self._key)
        logger.warning("Open trades cleared", account_id=self._account_id)
