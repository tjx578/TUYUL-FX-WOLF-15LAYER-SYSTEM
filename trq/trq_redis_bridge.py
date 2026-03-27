"""TRQ Redis Bridge — publish TRQ pre-move results to Redis.

Zone: trq/ — writes signals to Redis. No analysis authority.

Architecture
------------
  Pipeline pattern per symbol:
    HSET  wolf15:trq:premove:{SYM}          (latest snapshot, TTL=300s)
    RPUSH wolf15:trq:r3d_history:{SYM}      (R3D history, max=100, TTL=6h)
    LTRIM wolf15:trq:r3d_history:{SYM} -100 -1
    PUBLISH trq:premove:broadcast           (all-symbol broadcast channel)
    PUBLISH trq:premove:{SYM}               (per-symbol channel)

Also writes zone confluence when both Zone A and Zone B data are available.

Pydantic validation
-------------------
TRQPremoveSchema validates the payload before every Redis write.
  • conf12: Confidence [0, 1]
  • wlwci:  Wolf-Level Weighted Confluence Index [-1, 1]
"""

from __future__ import annotations

import time
from typing import Any

import orjson
from loguru import logger
from pydantic import BaseModel, field_validator

from core.redis_keys import (
    channel_confluence,
    channel_trq_premove,
    channel_trq_premove_symbol,
    trq_premove,
    trq_r3d_history,
    zone_confluence,
)

# ── Constants ─────────────────────────────────────────────────────────────────
_TRQ_PREMOVE_TTL_SEC = 300  # 5-minute freshness window for latest snapshot
_R3D_HISTORY_MAX = 100  # capped history size
_R3D_HISTORY_TTL_SEC = 21600  # 6 hours
_ZONE_CONFLUENCE_TTL_SEC = 300


# ══════════════════════════════════════════════════════════════════════════════
#  Schema
# ══════════════════════════════════════════════════════════════════════════════


class TRQPremoveSchema(BaseModel):
    """Validate a TRQ pre-move payload before writing to Redis."""

    symbol: str
    verdict: str
    r3d: float
    conf12: float
    wlwci: float
    quad_energy: float
    ts: float

    @field_validator("conf12")
    @classmethod
    def conf12_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"conf12 must be in [0, 1], got {v}")
        return v

    @field_validator("wlwci")
    @classmethod
    def wlwci_range(cls, v: float) -> float:
        if not (-1.0 <= v <= 1.0):
            raise ValueError(f"wlwci must be in [-1, 1], got {v}")
        return v


# ══════════════════════════════════════════════════════════════════════════════
#  TRQRedisBridge
# ══════════════════════════════════════════════════════════════════════════════


class TRQRedisBridge:
    """Publishes TRQ computation results to Redis.

    Designed to be called from TRQEngine after each computation cycle.

    Usage::

        bridge = TRQRedisBridge(redis)
        await bridge.publish(
            symbol="EURUSD",
            verdict="BULLISH",
            r3d=0.42,
            conf12=0.78,
            wlwci=0.35,
            quad_energy=1.23,
        )
    """

    def __init__(self, redis: Any) -> None:
        self._redis = redis
        self._publish_count: int = 0
        self._error_count: int = 0

    async def publish(
        self,
        symbol: str,
        verdict: str,
        r3d: float,
        conf12: float,
        wlwci: float,
        quad_energy: float,
    ) -> bool:
        """Validate and publish a TRQ pre-move snapshot to Redis.

        Returns True on success, False if validation or Redis write fails.
        """
        ts = time.time()
        payload_dict: dict[str, Any] = {
            "symbol": symbol,
            "verdict": verdict,
            "r3d": r3d,
            "conf12": conf12,
            "wlwci": wlwci,
            "quad_energy": quad_energy,
            "ts": ts,
        }

        try:
            TRQPremoveSchema(**payload_dict)
        except Exception as exc:
            self._error_count += 1
            logger.warning("[TRQRedisBridge] Schema validation failed {}: {}", symbol, exc)
            return False

        redis_payload: dict[str, str] = {k: str(v) for k, v in payload_dict.items()}
        r3d_entry = orjson.dumps({"r3d": r3d, "ts": ts}).decode()
        broadcast_json = orjson.dumps(payload_dict).decode()
        premove_key = trq_premove(symbol)
        history_key = trq_r3d_history(symbol)

        try:
            pipe = self._redis.pipeline()
            pipe.hset(premove_key, mapping=redis_payload)
            pipe.expire(premove_key, _TRQ_PREMOVE_TTL_SEC)
            pipe.rpush(history_key, r3d_entry)
            pipe.ltrim(history_key, -_R3D_HISTORY_MAX, -1)
            pipe.expire(history_key, _R3D_HISTORY_TTL_SEC)
            pipe.publish(channel_trq_premove(), broadcast_json)
            pipe.publish(channel_trq_premove_symbol(symbol), broadcast_json)
            await pipe.execute()

            self._publish_count += 1
            return True
        except Exception as exc:
            self._error_count += 1
            logger.warning("[TRQRedisBridge] Redis write failed {}: {}", symbol, exc)
            return False

    async def publish_zone_confluence(
        self,
        symbol: str,
        zone_a: dict[str, Any],
        zone_b: dict[str, Any],
    ) -> None:
        """Write zone A + B confluence snapshot to Redis.

        Parameters
        ----------
        zone_a:
            Micro-wave (M1/M5/M15) confluence data dict.
        zone_b:
            Macro-strategy (H1/H4/D1/W1) confluence data dict.
        """
        key = zone_confluence(symbol)
        payload: dict[str, str] = {
            "symbol": symbol,
            "zone_a": orjson.dumps(zone_a).decode(),
            "zone_b": orjson.dumps(zone_b).decode(),
            "ts": str(time.time()),
        }
        try:
            pipe = self._redis.pipeline()
            pipe.hset(key, mapping=payload)
            pipe.expire(key, _ZONE_CONFLUENCE_TTL_SEC)
            pipe.publish(channel_confluence(symbol), orjson.dumps(payload).decode())
            await pipe.execute()
        except Exception as exc:
            logger.warning("[TRQRedisBridge] Zone confluence write failed {}: {}", symbol, exc)

    def health(self) -> dict[str, Any]:
        """Return publish/error counts for monitoring."""
        return {
            "publish_count": self._publish_count,
            "error_count": self._error_count,
        }
