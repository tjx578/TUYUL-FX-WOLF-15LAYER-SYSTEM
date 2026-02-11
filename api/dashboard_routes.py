"""
Dashboard Trade Routes — FastAPI router for manual-first trade flow.

Endpoints:
  POST /api/v1/trades/take        — Trader takes a signal (system computes lot)
  POST /api/v1/trades/skip        — Trader skips a signal
  POST /api/v1/trades/confirm     — Trader confirms order placed at broker
  POST /api/v1/trades/close       — Trader manually closes a trade
  GET  /api/v1/trades/active      — List all active trades
  GET  /api/v1/trades/{trade_id}  — Get single trade detail
  GET  /api/v1/prices             — Get all live prices
  GET  /api/v1/prices/{symbol}    — Get single symbol price
  GET  /api/v1/accounts           — List accounts
  POST /api/v1/accounts           — Create account
  GET  /api/v1/accounts/{id}      — Get account detail
"""

from typing import List

from fastapi import APIRouter, HTTPException # pyright: ignore[reportMissingImports]
from pydantic import BaseModel, Field

from dashboard.account_manager import AccountManager
from dashboard.price_feed import PriceFeed
from dashboard.trade_ledger import TradeLedger
from journal.journal_router import JournalRouter
from journal.journal_schema import DecisionJournal, VerdictType
from risk.prop_firm import PropFirmRules
from schemas.trade_models import Trade, Account, TradeStatus, CloseReason
from utils.timezone_utils import now_utc

router = APIRouter()

# Service instances
_account_mgr = AccountManager()
_trade_ledger = TradeLedger()
_price_feed = PriceFeed()
_journal = JournalRouter()


# ========================
# REQUEST/RESPONSE MODELS
# ========================

class TakeSignalRequest(BaseModel):
    """Request to take a signal."""
    signal_id: str = Field(..., description="Source signal ID")
    account_id: str = Field(..., description="Account ID")
    pair: str = Field(..., description="Trading pair")
    direction: str = Field(..., description="BUY or SELL")
    entry: float = Field(..., gt=0, description="Entry price")
    sl: float = Field(..., gt=0, description="Stop loss")
    tp: float = Field(..., gt=0, description="Take profit")
    risk_percent: float = Field(..., gt=0, le=5.0, description="Risk % of balance")


class SkipSignalRequest(BaseModel):
    """Request to skip a signal."""
    signal_id: str = Field(..., description="Source signal ID")
    pair: str = Field(..., description="Trading pair")
    reason: str = Field(default="Manual skip", description="Reason for skipping")


class ConfirmOrderRequest(BaseModel):
    """Request to confirm order placed at broker."""
    trade_id: str = Field(..., description="Trade ID")


class CloseTradeRequest(BaseModel):
    """Request to manually close a trade."""
    trade_id: str = Field(..., description="Trade ID")
    reason: str = Field(default="Manual close", description="Reason for closing")


class CreateAccountRequest(BaseModel):
    """Request to create a new account."""
    name: str = Field(..., description="Account name")
    balance: float = Field(..., gt=0, description="Initial balance")
    prop_firm: bool = Field(default=False, description="Is prop firm account?")
    max_daily_dd_percent: float = Field(default=4.0, gt=0, description="Max daily DD %")
    max_total_dd_percent: float = Field(default=8.0, gt=0, description="Max total DD %")
    max_concurrent_trades: int = Field(default=1, gt=0, description="Max concurrent trades")


# ========================
# TRADE ENDPOINTS
# ========================

@router.post("/api/v1/trades/take")
async def take_signal(req: TakeSignalRequest) -> Trade:
    """
    Trader takes a signal — dashboard computes lot size and creates trade.

    Validates:
      - Account exists
      - Risk limits not breached
      - Prop firm rules if applicable
    """
    # Get account
    account = _account_mgr.get_account(req.account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account not found: {req.account_id}")

    # Check risk limits
    if account.prop_firm:
        prop_rules = PropFirmRules()
        max_risk = prop_rules.max_risk_allowed()
        if req.risk_percent > max_risk:
            raise HTTPException(
                status_code=400,
                detail=f"Risk {req.risk_percent}% exceeds prop firm limit {max_risk}%"
            )

    # Calculate risk amount
    risk_amount = account.balance * (req.risk_percent / 100.0)

    # Calculate lot size (simplified — actual would need pip value, etc.)
    # For now, use a placeholder calculation
    pip_distance = abs(req.entry - req.sl)
    lot_size = round(risk_amount / (pip_distance * 10), 2)  # Simplified

    # Create trade in INTENDED status
    trade = _trade_ledger.create_trade(
        signal_id=req.signal_id,
        account_id=req.account_id,
        pair=req.pair,
        direction=req.direction,
        risk_mode="FIXED",
        total_risk_percent=req.risk_percent,
        total_risk_amount=risk_amount,
        legs=[{
            "entry": req.entry,
            "sl": req.sl,
            "tp": req.tp,
            "lot": lot_size,
        }],
    )

    # Record J2 decision journal (trader took the signal)
    try:
        j2 = DecisionJournal(
            timestamp=now_utc(),
            pair=req.pair,
            setup_id=req.signal_id,
            wolf_30_score=0,  # Not available in manual flow
            f_score=0,
            t_score=0,
            fta_score=0,
            exec_score=0,
            tii_sym=0.0,
            integrity_index=0.0,
            monte_carlo_win=0.0,
            conf12=0.0,
            verdict=VerdictType.EXECUTE_BUY if req.direction == "BUY" else VerdictType.EXECUTE_SELL,
            confidence="MANUAL",
            wolf_status="MANUAL_TRADE",
            gates_passed=0,
            primary_rejection_reason=None,
        )
        _journal.record_decision(j2)
    except Exception:
        # Don't fail the trade if journal fails
        pass

    return trade


@router.post("/api/v1/trades/skip")
async def skip_signal(req: SkipSignalRequest) -> dict:
    """
    Trader skips a signal.

    Records decision in journal but does not create trade.
    """
    try:
        # Record J2 decision journal (trader skipped)
        j2 = DecisionJournal(
            timestamp=now_utc(),
            pair=req.pair,
            setup_id=req.signal_id,
            wolf_30_score=0,
            f_score=0,
            t_score=0,
            fta_score=0,
            exec_score=0,
            tii_sym=0.0,
            integrity_index=0.0,
            monte_carlo_win=0.0,
            conf12=0.0,
            verdict=VerdictType.NO_TRADE,
            confidence="MANUAL_SKIP",
            wolf_status="SKIPPED",
            gates_passed=0,
            primary_rejection_reason=req.reason,
        )
        _journal.record_decision(j2)
    except Exception:
        pass

    return {
        "status": "skipped",
        "signal_id": req.signal_id,
        "reason": req.reason,
    }


@router.post("/api/v1/trades/confirm")
async def confirm_order(req: ConfirmOrderRequest) -> Trade:
    """
    Trader confirms order placed at broker.

    Transitions trade from INTENDED → PENDING.
    """
    trade = _trade_ledger.get_trade(req.trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade not found: {req.trade_id}")

    # Update status
    success = _trade_ledger.update_status(req.trade_id, TradeStatus.PENDING)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid status transition")

    # Get updated trade
    trade = _trade_ledger.get_trade(req.trade_id)
    return trade # pyright: ignore[reportReturnType]


@router.post("/api/v1/trades/close")
async def close_trade(req: CloseTradeRequest) -> Trade:
    """
    Trader manually closes a trade.

    Transitions trade from OPEN → CLOSED with MANUAL_CLOSE reason.
    """
    trade = _trade_ledger.get_trade(req.trade_id)
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade not found: {req.trade_id}")

    # Update status
    success = _trade_ledger.update_status(
        req.trade_id,
        TradeStatus.CLOSED,
        close_reason=CloseReason.MANUAL_CLOSE,
        pnl=None  # P&L would come from broker
    )
    if not success:
        raise HTTPException(status_code=400, detail="Invalid status transition")

    # Get updated trade
    trade = _trade_ledger.get_trade(req.trade_id)
    return trade # pyright: ignore[reportReturnType]


@router.get("/api/v1/trades/active")
async def get_active_trades() -> List[Trade]:
    """Get all active trades."""
    return _trade_ledger.get_active_trades()


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
async def list_accounts() -> List[Account]:
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
