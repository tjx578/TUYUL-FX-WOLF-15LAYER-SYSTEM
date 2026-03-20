"""
Dashboard Auxiliary Routes — prices and trade-by-ID read endpoints.

These are the UNIQUE endpoints not provided by write_router (trade_input_api.py).
The mutable trade lifecycle (take/skip/confirm/close) lives exclusively in:
  dashboard/backend/trade_input_api.py → write_router

Endpoints (this file):
  GET  /api/v1/trades/{trade_id}  - Get single trade detail (read-only)
  GET  /api/v1/prices             - Get all live prices
  GET  /api/v1/prices/{symbol}    - Get single symbol price
    NOTE: account read endpoints now live in api/accounts_router.py (read-only).

NOTE: Do NOT add POST /api/v1/trades/* here — those belong to write_router only.
      Adding them here would create duplicate endpoints and double-execution risk.
"""

from fastapi import APIRouter, Depends, HTTPException

from dashboard.price_feed import PriceFeed
from dashboard.trade_ledger import TradeLedger
from schemas.trade_models import Trade

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
