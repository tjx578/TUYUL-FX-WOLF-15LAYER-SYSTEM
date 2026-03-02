"""Signal Registry — global L14 signal store.

Store the latest signal per pair published by the engine.
Allocation service reads from here before computing per-account plans.
No decision logic. Read/write only.
Engine pushes here; allocation layer reads here.
"""
from __future__ import annotations

import json
from threading import Lock
from typing import Any, Optional

from loguru import logger

from storage.redis_client import RedisClient

_REGISTRY_KEY_PREFIX = "signal:registry:"
_REGISTRY_INDEX_KEY = "signal:registry:index"


class SignalRegistry:
    """Thread-safe global signal registry backed by Redis."""

    _instance: Optional["SignalRegistry"] = None
    _lock = Lock()

    def __new__(cls) -> "SignalRegistry":
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._redis = RedisClient()
        return cls._instance

    def publish(self, signal: dict[str, Any]) -> None:
        """Store latest signal for its pair/symbol."""
        symbol = signal.get("symbol") or signal.get("pair", "UNKNOWN")
        key = f"{_REGISTRY_KEY_PREFIX}{symbol}"
        self._redis.set(key, json.dumps(signal), ex=3600)
        self._redis.client.sadd(_REGISTRY_INDEX_KEY, symbol)
        logger.debug(f"SignalRegistry: published signal for {symbol}")

    def get(self, symbol: str) -> Optional[dict[str, Any]]:
        """Retrieve latest signal for a symbol."""
        raw = self._redis.get(f"{_REGISTRY_KEY_PREFIX}{symbol}")
        return json.loads(raw) if raw else None

    def list_symbols(self) -> list[str]:
        """Return all symbols with registered signals."""
        members = self._redis.client.smembers(_REGISTRY_INDEX_KEY)
        return sorted(members) if members else []

    def all_signals(self) -> list[dict[str, Any]]:
        """Return all current signals."""
        results = []
        for symbol in self.list_symbols():
            sig = self.get(symbol)
            if sig:
                results.append(sig)
        return results
