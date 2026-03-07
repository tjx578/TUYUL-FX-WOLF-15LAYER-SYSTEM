"""
TUYUL FX Wolf-15 — Market Instruments Routes
==============================================
NEW ENDPOINTS:
  GET /api/v1/instruments                    → All instruments + metadata
  GET /api/v1/instruments/{symbol}           → Detail per symbol
  GET /api/v1/instruments/{symbol}/regime    → Current volatility regime
  GET /api/v1/instruments/{symbol}/sessions  → Trading hours + session strength
"""

import contextlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import redis as redis_lib
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException

from api.middleware.auth import verify_token
from infrastructure.redis_client import get_async_redis

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/instruments",
    tags=["instruments"],
    dependencies=[Depends(verify_token)],
)


def _get_redis() -> None:
    """DEPRECATED — use ``get_async_redis`` dependency instead."""
    raise NotImplementedError(
        "_get_redis() is removed. Inject via Depends(get_async_redis)."
    )


# ─── Static instrument catalog ────────────────────────────────────────────────

INSTRUMENT_CATALOG: dict[str, dict] = {
    "XAUUSD": {
        "symbol": "XAUUSD", "name": "Gold vs US Dollar",
        "category": "METAL", "contract_size": 100,
        "pip_size": 0.01, "pip_value_usd": 1.0,
        "typical_spread": 0.3, "leverage_max": 100,
        "commission_per_lot": 0.0,
        "sessions": ["ASIA", "LONDON", "NY"],
        "market_hours_utc": "Sun 22:00 – Fri 21:00",
        "volatility_tier": "HIGH",
        "wolf15_enabled": True,
    },
    "EURUSD": {
        "symbol": "EURUSD", "name": "Euro vs US Dollar",
        "category": "MAJOR", "contract_size": 100000,
        "pip_size": 0.0001, "pip_value_usd": 10.0,
        "typical_spread": 0.1, "leverage_max": 500,
        "commission_per_lot": 3.5,
        "sessions": ["LONDON", "NY"],
        "market_hours_utc": "Sun 22:00 – Fri 22:00",
        "volatility_tier": "MEDIUM",
        "wolf15_enabled": True,
    },
    "GBPUSD": {
        "symbol": "GBPUSD", "name": "British Pound vs US Dollar",
        "category": "MAJOR", "contract_size": 100000,
        "pip_size": 0.0001, "pip_value_usd": 10.0,
        "typical_spread": 0.2, "leverage_max": 500,
        "commission_per_lot": 3.5,
        "sessions": ["LONDON", "NY"],
        "market_hours_utc": "Sun 22:00 – Fri 22:00",
        "volatility_tier": "HIGH",
        "wolf15_enabled": True,
    },
    "USDJPY": {
        "symbol": "USDJPY", "name": "US Dollar vs Japanese Yen",
        "category": "MAJOR", "contract_size": 100000,
        "pip_size": 0.01, "pip_value_usd": 9.09,
        "typical_spread": 0.1, "leverage_max": 500,
        "commission_per_lot": 3.5,
        "sessions": ["ASIA", "LONDON", "NY"],
        "market_hours_utc": "Sun 22:00 – Fri 22:00",
        "volatility_tier": "MEDIUM",
        "wolf15_enabled": True,
    },
    "AUDUSD": {
        "symbol": "AUDUSD", "name": "Australian Dollar vs US Dollar",
        "category": "MAJOR", "contract_size": 100000,
        "pip_size": 0.0001, "pip_value_usd": 10.0,
        "typical_spread": 0.2, "leverage_max": 500,
        "commission_per_lot": 3.5,
        "sessions": ["ASIA", "LONDON"],
        "market_hours_utc": "Sun 22:00 – Fri 22:00",
        "volatility_tier": "MEDIUM",
        "wolf15_enabled": True,
    },
    "GBPJPY": {
        "symbol": "GBPJPY", "name": "British Pound vs Japanese Yen",
        "category": "CROSS", "contract_size": 100000,
        "pip_size": 0.01, "pip_value_usd": 9.09,
        "typical_spread": 0.5, "leverage_max": 200,
        "commission_per_lot": 3.5,
        "sessions": ["LONDON", "NY"],
        "market_hours_utc": "Sun 22:00 – Fri 22:00",
        "volatility_tier": "VERY_HIGH",
        "wolf15_enabled": True,
    },
    "US30": {
        "symbol": "US30", "name": "Dow Jones Industrial Average",
        "category": "INDEX", "contract_size": 1,
        "pip_size": 1.0, "pip_value_usd": 1.0,
        "typical_spread": 3.0, "leverage_max": 100,
        "commission_per_lot": 0.0,
        "sessions": ["NY"],
        "market_hours_utc": "Mon 13:30 – Fri 22:00",
        "volatility_tier": "HIGH",
        "wolf15_enabled": False,
    },
    "BTCUSD": {
        "symbol": "BTCUSD", "name": "Bitcoin vs US Dollar",
        "category": "CRYPTO", "contract_size": 1,
        "pip_size": 1.0, "pip_value_usd": 1.0,
        "typical_spread": 50.0, "leverage_max": 20,
        "commission_per_lot": 0.0,
        "sessions": ["24/7"],
        "market_hours_utc": "24/7",
        "volatility_tier": "EXTREME",
        "wolf15_enabled": False,
    },
}

# Session strength by session name
SESSION_STRENGTH: dict[str, dict] = {
    "ASIA":   {"strength": 0.5, "start_utc": "22:00", "end_utc": "08:00", "typical_range_pips": 40},
    "LONDON": {"strength": 1.0, "start_utc": "07:00", "end_utc": "16:00", "typical_range_pips": 80},
    "NY":     {"strength": 0.9, "start_utc": "13:00", "end_utc": "22:00", "typical_range_pips": 70},
    "OVERLAP": {"strength": 1.0, "start_utc": "13:00", "end_utc": "16:00", "typical_range_pips": 100},
}


def _get_current_session() -> str:
    hour = datetime.now(timezone.utc).hour
    if 7 <= hour < 13:
        return "LONDON"
    if 13 <= hour < 16:
        return "OVERLAP"
    if 13 <= hour < 22:
        return "NY"
    return "ASIA"


async def _get_live_verdict(r: aioredis.Redis, symbol: str) -> Optional[dict]:
    with contextlib.suppress(Exception):
        raw = await r.get(f"DASHBOARD:VERDICT:{symbol}")
        if raw:
            return json.loads(raw)
    return None


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.get("")
async def list_instruments() -> dict:
    """List all instruments with metadata + live Wolf-15 status."""
    r: aioredis.Redis = await get_async_redis()
    result = []
    for symbol, info in INSTRUMENT_CATALOG.items():
        item = dict(info)
        verdict = await _get_live_verdict(r, symbol)
        if verdict:
            item["live_verdict"] = verdict.get("verdict")
            item["live_confidence"] = verdict.get("confidence")
            item["live_direction"] = verdict.get("direction")
        else:
            item["live_verdict"] = None
            item["live_confidence"] = None
            item["live_direction"] = None
        item["current_session"] = _get_current_session()
        result.append(item)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "count": len(result),
        "instruments": result,
    }


@router.get("/{symbol}")
async def instrument_detail(symbol: str) -> dict:
    symbol_upper = symbol.upper()
    info = INSTRUMENT_CATALOG.get(symbol_upper)
    if not info:
        raise HTTPException(status_code=404, detail=f"Instrument {symbol_upper} not found")

    r: aioredis.Redis = await get_async_redis()
    detail = dict(info)

    # Live data from Redis
    verdict = await _get_live_verdict(r, symbol_upper)
    if verdict:
        detail["live"] = {
            "verdict": verdict.get("verdict"),
            "confidence": verdict.get("confidence"),
            "direction": verdict.get("direction"),
            "entry": verdict.get("entry_price"),
            "sl": verdict.get("stop_loss"),
            "tp": verdict.get("take_profit_1"),
            "scores": verdict.get("scores"),
            "gates": verdict.get("gates"),
        }

    # Live price
    with contextlib.suppress(Exception):
        raw_price = await r.get(f"PRICE:{symbol_upper}")
        if raw_price:
            detail["price"] = json.loads(raw_price)

    detail["current_session"] = _get_current_session()
    detail["timestamp"] = datetime.now(timezone.utc).isoformat()
    return detail


@router.get("/{symbol}/regime")
async def instrument_regime(symbol: str) -> dict:
    """Current volatility regime for instrument (from L1-L5 analysis layers)."""
    symbol_upper = symbol.upper()
    r: aioredis.Redis = await get_async_redis()

    regime_data: dict = {
        "symbol": symbol_upper,
        "regime": "UNKNOWN",
        "volatility": "UNKNOWN",
        "trend": "UNKNOWN",
        "session": _get_current_session(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        # Read from L1 context bus
        raw = await r.get(f"CONTEXT:{symbol_upper}:REGIME")
        if raw:
            regime_data.update(json.loads(raw))
        else:
            # Fallback: extract from L12 verdict context
            verdict = await _get_live_verdict(r, symbol_upper)
            if verdict and verdict.get("scores"):
                scores = verdict["scores"]
                regime_data["regime"] = scores.get("regime", "UNKNOWN")
                regime_data["session"] = scores.get("session", _get_current_session())
    except Exception as exc:
        logger.warning("Regime data error for %s: %s", symbol_upper, exc)

    return regime_data


@router.get("/{symbol}/sessions")
async def instrument_sessions(symbol: str) -> dict:
    """Trading hours and session strength per instrument."""
    symbol_upper = symbol.upper()
    info = INSTRUMENT_CATALOG.get(symbol_upper, {})

    symbol_sessions = info.get("sessions", ["LONDON", "NY"])
    current = _get_current_session()

    session_details = []
    for s in ["ASIA", "LONDON", "OVERLAP", "NY"]:
        active = s in symbol_sessions or (s == "OVERLAP" and "LONDON" in symbol_sessions)
        strength_info = SESSION_STRENGTH.get(s, {})
        session_details.append({
            "session": s,
            "active_for_symbol": active,
            "is_current": s == current,
            "strength": strength_info.get("strength", 0.5) if active else 0.0,
            "start_utc": strength_info.get("start_utc"),
            "end_utc": strength_info.get("end_utc"),
            "typical_range_pips": strength_info.get("typical_range_pips"),
        })

    return {
        "symbol": symbol_upper,
        "current_session": current,
        "market_hours_utc": info.get("market_hours_utc", "N/A"),
        "sessions": session_details,
    }
