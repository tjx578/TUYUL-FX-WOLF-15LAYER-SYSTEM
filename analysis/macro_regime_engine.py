from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import orjson

from loguru import logger

from storage.redis_client import redis_client as redis_client_default


class MacroRegimeEngine:
    """Simple Macro Regime Engine that reads MN history and writes regime to Redis.

    This implementation is intentionally small and deterministic for tests.
    """

    def __init__(self, redis_client: redis_client_default | None = None) -> None: # pyright: ignore[reportInvalidTypeForm]
        self.redis = redis_client or redis_client_default

    def _load_mn_history(self, symbol: str, max_items: int = 240) -> list[dict[str, Any]]:
        key = f"wolf15:candle:{symbol}:MN:history"
        try:
            raw = self.redis.client.lrange(key, 0, -1)
            if not raw:
                return []
            history = [orjson.loads(item) for item in raw] # pyright: ignore[reportGeneralTypeIssues]
            return history[-max_items:]
        except Exception as exc:
            logger.error(f"Failed to load MN history for {symbol}: {exc}")
            return []

    def _compute_regime(self, mn_history: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute a lightweight regime signal from MN history.

        Strategy (simple):
        - If most recent close > previous close -> BULLISH_EXPANSION
        - Else -> BEARISH_CONTRACTION
        """
        if not mn_history or len(mn_history) < 2:
            return {"type": "UNKNOWN", "bias": "NEUTRAL"}

        last = mn_history[-1]
        prev = mn_history[-2]

        try:
            last_close = float(last.get("close", 0))
            prev_close = float(prev.get("close", 0))
        except Exception:
            return {"type": "UNKNOWN", "bias": "NEUTRAL"}

        if last_close > prev_close:
            return {"type": "BULLISH_EXPANSION", "bias": "BULLISH"}
        return {"type": "BEARISH_CONTRACTION", "bias": "BEARISH"}

    def update_macro_state(self, symbol: str) -> dict[str, Any]:
        """Load MN history, compute regime, and write to Redis hash.

        Returns the regime dict written.
        """
        mn_history = self._load_mn_history(symbol)
        regime = self._compute_regime(mn_history)

        # Enrich with timestamp
        regime_payload = {
            "type": regime.get("type", "UNKNOWN"),
            "bias": regime.get("bias", "NEUTRAL"),
            "updated_at": datetime.now(UTC).isoformat(),
        }

        try:
            key = f"regime:macro:{symbol}"
            self.redis.hset(key, mapping=regime_payload)
            logger.info(f"Macro regime updated for {symbol}: {regime_payload}")
        except Exception as exc:
            logger.error(f"Failed to write macro regime for {symbol}: {exc}")

        return regime_payload
