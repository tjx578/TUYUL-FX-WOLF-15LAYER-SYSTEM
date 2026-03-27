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

from fastapi import APIRouter, Depends, HTTPException

from schemas.trade_models import Trade
from storage.price_feed import PriceFeed
from storage.trade_ledger import TradeLedger

from .middleware.auth import verify_token

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
