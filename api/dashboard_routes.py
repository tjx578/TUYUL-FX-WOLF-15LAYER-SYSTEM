"""
Dashboard Auxiliary Routes — prices, accounts, and trade-by-ID read endpoints.

These are the UNIQUE endpoints not provided by write_router (trade_input_api.py).
The mutable trade lifecycle (take/skip/confirm/close) lives exclusively in:
  dashboard/backend/trade_input_api.py → write_router

Endpoints (this file):
  GET  /api/v1/trades/{trade_id}  - Get single trade detail (read-only)
  GET  /api/v1/prices             - Get all live prices
  GET  /api/v1/prices/{symbol}    - Get single symbol price
  GET  /api/v1/accounts           - List accounts
  POST /api/v1/accounts           - Create account
  GET  /api/v1/accounts/{id}      - Get account detail

NOTE: Do NOT add POST /api/v1/trades/* here — those belong to write_router only.
      Adding them here would create duplicate endpoints and double-execution risk.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from dashboard.account_manager import AccountManager
from dashboard.price_feed import PriceFeed
from dashboard.trade_ledger import TradeLedger
from schemas.trade_models import Account, Trade

router = APIRouter()

# Service instances (read path only — no journal/risk side-effects here)
_account_mgr = AccountManager()
_trade_ledger = TradeLedger()
_price_feed = PriceFeed()


# ========================
# REQUEST MODELS
# ========================


class CreateAccountRequest(BaseModel):
    """Request to create a new account."""

    name: str = Field(..., description="Account name")
    balance: float = Field(..., gt=0, description="Initial balance")
    prop_firm: bool = Field(default=False, description="Is prop firm account?")
    max_daily_dd_percent: float = Field(default=4.0, gt=0, description="Max daily DD %")
    max_total_dd_percent: float = Field(default=8.0, gt=0, description="Max total DD %")
    max_concurrent_trades: int = Field(default=1, gt=0, description="Max concurrent trades")


# ========================
# TRADE READ ENDPOINT
# (write lifecycle: POST /trades/* → write_router in trade_input_api.py)
# ========================


@router.get("/api/v1/trades/{trade_id}")
async def get_trade(trade_id: str) -> Trade:
    """Get single trade by ID."""
    trade = _trade_ledger.get_trade(trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade not found: {trade_id}")
    return trade


# ========================
# PRICE ENDPOINTS
# ========================


@router.get("/api/v1/prices")
async def get_all_prices() -> dict:
    """Get all live prices."""
    prices = _price_feed.get_all_prices()
    return {"prices": prices, "count": len(prices)}


@router.get("/api/v1/prices/{symbol}")
async def get_price(symbol: str) -> dict:
    """Get single symbol price."""
    price = _price_feed.get_price(symbol.upper())
    if not price:
        raise HTTPException(status_code=404, detail=f"No price data for {symbol}")
    return {"symbol": symbol.upper(), "price": price}


# ========================
# ACCOUNT ENDPOINTS
# ========================


@router.get("/api/v1/accounts")
async def list_accounts() -> list[Account]:
    """List all accounts."""
    return _account_mgr.list_accounts()


@router.post("/api/v1/accounts")
async def create_account(req: CreateAccountRequest) -> Account:
    """Create a new account."""
    account = _account_mgr.create_account(
        name=req.name,
        balance=req.balance,
        prop_firm=req.prop_firm,
        max_daily_dd_percent=req.max_daily_dd_percent,
        max_total_dd_percent=req.max_total_dd_percent,
        max_concurrent_trades=req.max_concurrent_trades,
    )
    return account


@router.get("/api/v1/accounts/{account_id}")
async def get_account(account_id: str) -> Account:
    """Get account by ID."""
    account = _account_mgr.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")
    return account
