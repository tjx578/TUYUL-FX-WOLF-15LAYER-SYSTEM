"""
Dashboard Auxiliary Routes — prices, trade-by-ID, and candle feed status endpoints.

These are the UNIQUE endpoints not provided by write_router (trade_input_api.py).
The mutable trade lifecycle (take/skip/confirm/close) lives exclusively in:
  dashboard/backend/trade_input_api.py → write_router

Endpoints (this file):
  GET  /api/v1/trades/{trade_id}     - Get single trade detail (read-only)
  GET  /api/v1/prices                - Get all live prices
  GET  /api/v1/prices/{symbol}       - Get single symbol price
  GET  /api/v1/candles/feed-status   - Candle pipeline feed status (ingest health + per-symbol freshness)
    NOTE: account read endpoints now live in api/accounts_router.py (read-only).

NOTE: Do NOT add POST /api/v1/trades/* here — those belong to write_router only.
      Adding them here would create duplicate endpoints and double-execution risk.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from schemas.trade_models import Trade
from storage.l12_cache import get_verdict
from storage.price_feed import PriceFeed
from storage.trade_ledger import TradeLedger

from .middleware.auth import verify_token
from .verdict_normalization import (
    admission_state,
    quality_state,
    reason_code,
    snapshot_age_seconds,
    verdict_state,
)

router = APIRouter(dependencies=[Depends(verify_token)])

# Service instances (read path only — no journal/risk side-effects here)
_trade_ledger = TradeLedger()
_price_feed = PriceFeed()


# ========================
# TRADE READ ENDPOINT
# (write lifecycle: POST /trades/* → write_router in trade_input_api.py)
# ========================


@router.get("/api/v1/trades/{trade_id}")
async def get_trade(trade_id: str) -> Trade:
    """Get single trade by ID."""
    trade = await _trade_ledger.get_trade_async(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade not found: {trade_id}")
    return trade


# ========================
# PRICE ENDPOINTS
# ========================


@router.get("/api/v1/prices")
async def get_all_prices() -> dict:
    """Get all live prices."""
    prices = await _price_feed.get_all_prices_async()
    return {"prices": prices, "count": len(prices)}


@router.get("/api/v1/prices/{symbol}")
async def get_price(symbol: str) -> dict:
    """Get single symbol price."""
    price = await _price_feed.get_price_async(symbol.upper())
    if not price:
        raise HTTPException(status_code=404, detail=f"No price data for {symbol}")
    return {"symbol": symbol.upper(), "price": price}


# ========================
# CANDLE FEED STATUS
# ========================


@router.get("/api/v1/candles/feed-status")
async def candle_feed_status() -> dict:
    """Return candle pipeline feed status — ingest health + per-symbol freshness.

    This is the REST polling fallback for when the candle WebSocket is
    disconnected. The same ``feed_meta`` payload is included in each
    ``candle.forming`` WS event for connected clients.

    Response shape::

        {
            "ingest_status": "HEALTHY" | "DEGRADED" | "NO_PRODUCER" | "UNKNOWN",
            "provider_connected": true | false,
            "symbols": {
                "EURUSD": { "feed_status": "LIVE", "age_seconds": 2.3 },
                "GBPUSD": { "feed_status": "STALE", "age_seconds": 185.0 },
                ...
            }
        }
    """
    try:
        from api.ws_routes import _candle_agg

        return await _candle_agg.fetch_feed_meta_async()
    except Exception:
        return {
            "ingest_status": "UNKNOWN",
            "provider_connected": False,
            "symbols": {},
        }


# ========================
# DASHBOARD PAIR STATES
# (read-only projection for the owner dashboard Pair Radar)
# ========================


@router.get("/api/v1/dashboard/pair-states")
def dashboard_pair_states() -> dict[str, Any]:
    """Slim, viewer-safe per-pair verdict state.

    Composed here rather than in the browser so that governance normalization
    stays on this side of the boundary: ``admission`` is the action this service
    derives from a record, not something a client infers from an absent field.

    Only declared values are published.  A verdict, admission or reason outside
    its declared set is reported as ``null`` -- unmeasured, never guessed -- and
    no confidence, score, gate, execution or diagnostic field is included.

    The response is the available cached-verdict subset: at most one row per
    configured pair, and fewer while a pair is warming up, its cache has
    expired, or it has produced no verdict yet.
    """
    # Imported here: the pair universe is built at import time by the L12 routes,
    # and this endpoint must report exactly the same set as /api/v1/verdict/all.
    from .l12_routes import AVAILABLE_PAIRS  # noqa: PLC0415
    from .redis_context_reader import RedisContextReader  # noqa: PLC0415

    reader: Any = RedisContextReader()
    source_ok = True
    items: list[dict[str, Any]] = []

    for pair_info in AVAILABLE_PAIRS:
        symbol = pair_info.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            continue

        raw: dict[str, Any] | None = None
        try:
            raw = get_verdict(symbol)
        except Exception:
            source_ok = False

        try:
            warmup_ready = bool(reader.check_warmup(symbol).get("ready", False))
        except Exception:
            source_ok = False
            warmup_ready = False

        age = snapshot_age_seconds(raw)
        items.append(
            {
                "symbol": symbol,
                "verdict": verdict_state(raw),
                "admission": admission_state(raw),
                "reason_code": reason_code(raw),
                "age_seconds": age,
                "quality": quality_state(age),
                "warmup_ready": warmup_ready,
                "active": bool(pair_info.get("enabled", True)),
                "snapshot_present": raw is not None,
            }
        )

    items.sort(key=lambda item: str(item["symbol"]))
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "source_ok": source_ok,
        "count": len(items),
        "items": items,
    }
