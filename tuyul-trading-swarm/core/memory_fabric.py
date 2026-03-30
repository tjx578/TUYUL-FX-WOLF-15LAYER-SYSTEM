"""Memory Fabric — shared persistent memory untuk semua agent dalam swarm.

Namespace keys:
  tuyul:memory:session_bias          -> bias instrumen per session
  tuyul:memory:active_watchlist      -> setup aktif dalam watchlist
  tuyul:memory:rejected_reasons      -> pattern alasan penolakan
  tuyul:memory:psychology_warnings   -> psychology/discipline alerts
  tuyul:memory:audit_flags           -> flag dari audit agent
  tuyul:memory:handoff:<shift_id>    -> handoff summary per shift
  tuyul:memory:decisions:<date>      -> semua decision hari ini
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from loguru import logger

from infrastructure.redis_client import get_async_redis

PREFIX = os.getenv("REDIS_PREFIX", "tuyul")
TTL_DECISION = int(os.getenv("MEMORY_DECISION_TTL_SEC", str(60 * 60 * 48)))  # 48 jam
TTL_WATCHLIST = int(os.getenv("MEMORY_WATCHLIST_TTL_SEC", str(60 * 60 * 12)))  # 12 jam
TTL_HANDOFF = int(os.getenv("MEMORY_HANDOFF_TTL_SEC", str(60 * 60 * 24 * 7)))  # 7 hari


class MemoryFabric:
    """Shared memory layer — Redis-backed, diakses semua agent."""

    # ──────────────────────────────────────────────
    # SESSION BIAS
    # ──────────────────────────────────────────────
    async def set_session_bias(self, instrument: str, session: str, bias: str) -> None:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:session_bias:{instrument}:{session}"
        await r.setex(key, TTL_DECISION, bias)

    async def get_session_bias(self, instrument: str, session: str) -> Optional[str]:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:session_bias:{instrument}:{session}"
        return await r.get(key)

    # ──────────────────────────────────────────────
    # WATCHLIST
    # ──────────────────────────────────────────────
    async def add_watchlist(self, entry: dict[str, Any]) -> None:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:active_watchlist"
        candidate_id = entry.get("candidate_id", "unknown")
        await r.hset(key, candidate_id, json.dumps(entry))
        await r.expire(key, TTL_WATCHLIST)
        logger.info(f"[Memory] Watchlist added: {candidate_id}")

    async def remove_watchlist(self, candidate_id: str) -> None:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:active_watchlist"
        await r.hdel(key, candidate_id)
        logger.info(f"[Memory] Watchlist removed: {candidate_id}")

    async def get_all_watchlist(self) -> list[dict[str, Any]]:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:active_watchlist"
        raw = await r.hgetall(key)
        return [json.loads(v) for v in raw.values()]

    # ──────────────────────────────────────────────
    # PSYCHOLOGY WARNINGS
    # ──────────────────────────────────────────────
    async def set_psychology_warning(self, level: str, reason: str) -> None:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:psychology_warnings"
        entry = json.dumps({"level": level, "reason": reason, "at": datetime.utcnow().isoformat()})
        await r.lpush(key, entry)
        await r.ltrim(key, 0, 49)  # keep last 50

    async def get_psychology_warnings(self, limit: int = 10) -> list[dict[str, Any]]:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:psychology_warnings"
        raw = await r.lrange(key, 0, limit - 1)
        return [json.loads(v) for v in raw]

    async def clear_psychology_warnings(self) -> None:
        r = await get_async_redis()
        await r.delete(f"{PREFIX}:memory:psychology_warnings")

    # ──────────────────────────────────────────────
    # AUDIT FLAGS
    # ──────────────────────────────────────────────
    async def add_audit_flag(self, flag: dict[str, Any]) -> None:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:audit_flags"
        await r.lpush(key, json.dumps(flag))
        await r.ltrim(key, 0, 99)

    async def get_audit_flags(self, limit: int = 20) -> list[dict[str, Any]]:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:audit_flags"
        raw = await r.lrange(key, 0, limit - 1)
        return [json.loads(v) for v in raw]

    # ──────────────────────────────────────────────
    # DECISIONS
    # ──────────────────────────────────────────────
    async def store_decision(self, decision: dict[str, Any]) -> None:
        r = await get_async_redis()
        date_key = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"{PREFIX}:memory:decisions:{date_key}"
        packet_id = decision.get("packet_id", "unknown")
        await r.hset(key, packet_id, json.dumps(decision))
        await r.expire(key, TTL_DECISION)

    async def get_decisions_today(self) -> list[dict[str, Any]]:
        r = await get_async_redis()
        date_key = datetime.utcnow().strftime("%Y-%m-%d")
        key = f"{PREFIX}:memory:decisions:{date_key}"
        raw = await r.hgetall(key)
        return [json.loads(v) for v in raw.values()]

    async def get_decisions_by_date(self, date_str: str) -> list[dict[str, Any]]:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:decisions:{date_str}"
        raw = await r.hgetall(key)
        return [json.loads(v) for v in raw.values()]

    # ──────────────────────────────────────────────
    # REJECTED SETUP PATTERNS
    # ──────────────────────────────────────────────
    async def record_rejection_reason(self, instrument: str, reason: str) -> None:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:rejected_reasons:{instrument}"
        await r.lpush(key, json.dumps({"reason": reason, "at": datetime.utcnow().isoformat()}))
        await r.ltrim(key, 0, 99)
        await r.expire(key, TTL_DECISION)

    async def get_rejection_patterns(self, instrument: str) -> list[dict[str, Any]]:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:rejected_reasons:{instrument}"
        raw = await r.lrange(key, 0, -1)
        return [json.loads(v) for v in raw]

    # ──────────────────────────────────────────────
    # SHIFT HANDOFF
    # ──────────────────────────────────────────────
    async def store_handoff(self, shift_id: str, summary: dict[str, Any]) -> None:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:handoff:{shift_id}"
        await r.set(key, json.dumps(summary))
        await r.expire(key, TTL_HANDOFF)
        logger.info(f"[Memory] Handoff stored: {shift_id}")

    async def get_last_handoff(self) -> Optional[dict[str, Any]]:
        r = await get_async_redis()
        pattern = f"{PREFIX}:memory:handoff:*"
        keys = await r.keys(pattern)
        if not keys:
            return None
        keys.sort(reverse=True)
        raw = await r.get(keys[0])
        return json.loads(raw) if raw else None

    # ──────────────────────────────────────────────
    # OPEN TRADE STATE
    # ──────────────────────────────────────────────
    async def set_open_trade(self, trade_id: str, trade_data: dict[str, Any]) -> None:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:open_trades"
        await r.hset(key, trade_id, json.dumps(trade_data))

    async def close_trade(self, trade_id: str) -> None:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:open_trades"
        await r.hdel(key, trade_id)

    async def get_open_trades(self) -> list[dict[str, Any]]:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:open_trades"
        raw = await r.hgetall(key)
        return [json.loads(v) for v in raw.values()]

    # ──────────────────────────────────────────────
    # UPCOMING EVENTS
    # ──────────────────────────────────────────────
    async def set_upcoming_events(self, events: list[dict[str, Any]]) -> None:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:upcoming_events"
        await r.set(key, json.dumps(events))
        await r.expire(key, 3600)

    async def get_upcoming_events(self) -> list[dict[str, Any]]:
        r = await get_async_redis()
        key = f"{PREFIX}:memory:upcoming_events"
        raw = await r.get(key)
        return json.loads(raw) if raw else []


_memory_fabric: MemoryFabric | None = None


def get_memory_fabric() -> MemoryFabric:
    global _memory_fabric
    if _memory_fabric is None:
        _memory_fabric = MemoryFabric()
    return _memory_fabric
