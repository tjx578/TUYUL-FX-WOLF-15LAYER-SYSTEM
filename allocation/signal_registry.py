"""Signal Registry — global L14 signal store.

All L14 outputs must be persisted here first before allocation/execution.
Signals are global and account-agnostic.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any, cast
from uuid import uuid4

from loguru import logger

from storage.redis_client import RedisClient

_REGISTRY_KEY_PREFIX = "signal:registry:id:"
_REGISTRY_INDEX_KEY = "signal:registry:index"
_SYMBOL_INDEX_KEY = "signal:registry:symbol:index"


@dataclass(frozen=True)
class SignalRecord:
    """Global account-agnostic signal record."""

    signal_id: str
    pair: str
    verdict: str
    gates_json: dict[str, Any] = field(default_factory=dict)
    execution_plan_json: dict[str, Any] = field(default_factory=dict)
    status: str = "OPEN"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SignalRecord:
        pair = str(payload.get("pair") or payload.get("symbol") or "UNKNOWN").upper()
        execution_plan = dict(payload.get("execution_plan_json") or {})
        if not execution_plan:
            execution_plan = {
                "entry_price": payload.get("entry_price", payload.get("entry")),
                "stop_loss": payload.get("stop_loss"),
                "take_profit_1": payload.get("take_profit_1", payload.get("tp1")),
                "order_type": payload.get("order_type", "PENDING_ONLY"),
                "execution_mode": payload.get("execution_mode", "TP1_ONLY"),
            }

        return cls(
            signal_id=str(payload.get("signal_id") or payload.get("id") or uuid4().hex),
            pair=pair,
            verdict=str(payload.get("verdict", "HOLD")),
            gates_json=dict(payload.get("gates_json") or {}),
            execution_plan_json=execution_plan,
            status=str(payload.get("status", "OPEN")).upper(),
            created_at=str(payload.get("created_at") or datetime.now(UTC).isoformat()),
        )


class SignalRegistry:
    """Thread-safe global signal registry backed by Redis."""

    _instance: SignalRegistry | None = None
    _lock = Lock()
    _redis: RedisClient

    def __new__(cls) -> SignalRegistry:
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._redis = RedisClient()
        return cls._instance

    def publish(self, signal: dict[str, Any]) -> dict[str, Any]:
        """Persist one global signal record and return normalized payload."""
        record = SignalRecord.from_payload(signal)
        payload = asdict(record)
        payload["symbol"] = record.pair
        payload["pair"] = record.pair

        key = f"{_REGISTRY_KEY_PREFIX}{record.signal_id}"
        self._redis.set(key, json.dumps(payload), ex=3600 * 24)
        self._redis.client.sadd(_REGISTRY_INDEX_KEY, record.signal_id)
        self._redis.client.sadd(_SYMBOL_INDEX_KEY, record.pair)
        logger.debug(f"SignalRegistry: published signal_id={record.signal_id} pair={record.pair}")
        return payload

    def get(self, symbol: str) -> dict[str, Any] | None:
        """Backward-compat: retrieve latest OPEN signal for a symbol."""
        symbol = symbol.upper().strip()
        for sig in self.get_latest(200):
            if str(sig.get("pair", "")).upper() == symbol and str(sig.get("status", "OPEN")) == "OPEN":
                return sig
        return None

    def get_by_id(self, signal_id: str) -> dict[str, Any] | None:
        """Retrieve signal by global signal_id."""
        raw = self._redis.get(f"{_REGISTRY_KEY_PREFIX}{signal_id}")
        return json.loads(raw) if raw else None

    def expire(self, signal_id: str) -> bool:
        """Mark signal as EXPIRED without deleting audit footprint."""
        current = self.get_by_id(signal_id)
        if not current:
            return False
        current["status"] = "EXPIRED"
        self._redis.set(f"{_REGISTRY_KEY_PREFIX}{signal_id}", json.dumps(current), ex=3600 * 24)
        return True

    def list_symbols(self) -> list[str]:
        """Return all symbols with registered signals."""
        members = cast(set[str], self._redis.client.smembers(_SYMBOL_INDEX_KEY))
        return sorted(members) if members else []

    def list_signal_ids(self) -> list[str]:
        members = cast(set[str], self._redis.client.smembers(_REGISTRY_INDEX_KEY))
        return sorted(members) if members else []

    def get_latest(self, n: int = 10) -> list[dict[str, Any]]:
        """Return latest signals sorted by created_at desc."""
        rows: list[dict[str, Any]] = []
        for signal_id in self.list_signal_ids():
            sig = self.get_by_id(signal_id)
            if sig:
                rows.append(sig)

        def _ts(item: dict[str, Any]) -> float:
            raw = str(item.get("created_at", ""))
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return 0.0

        rows.sort(key=_ts, reverse=True)
        return rows[: max(1, int(n))]

    def all_signals(self) -> list[dict[str, Any]]:
        """Return all current signals."""
        results: list[dict[str, Any]] = []
        for signal_id in self.list_signal_ids():
            sig = self.get_by_id(signal_id)
            if sig:
                results.append(sig)
        return results
