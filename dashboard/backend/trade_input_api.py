"""
Trade Input API - POST Endpoints for Dashboard

Provides write endpoints for:
- Receiving Layer 12 signals
- Calculating risk and lots
- Recording trade open/close
- Querying account state and trade ledger

All endpoints require JWT authentication.
"""

from datetime import datetime
from typing import Dict, List
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from dashboard.backend.auth import verify_token
from dashboard.backend.account_engine import AccountEngine
from dashboard.backend.risk_engine import RiskEngine
from dashboard.backend.schemas import (
    Layer12Signal,
    RiskCalculationRequest,
    RiskCalculationResult,
    TradeOpenRequest,
    TradeCloseRequest,
    AccountState,
    AccountCreate,
)
from execution.trade_state_enum import TradeState
from journal.journal_router import journal_router
from journal.journal_schema import (
    ReflectiveJournal,
    TradeOutcome,
    ProtectionAssessment,
)


# Router with auth dependency
write_router = APIRouter(
    prefix="/api/v1/dashboard",
    dependencies=[Depends(verify_token)],
    tags=["Dashboard Write Operations"],
)

# In-memory storage (replace with DB in production)
signal_pool: Dict[UUID, Dict] = {}
trade_ledger: Dict[str, Dict] = {}
account_registry: Dict[str, AccountEngine] = {}

# Risk engine singleton
risk_engine = RiskEngine()


@write_router.post("/signal/layer12", status_code=201)
def receive_layer12_signal(signal: Layer12Signal) -> Dict:
    """
    Receive Layer 12 signal from constitution.
    
    Stores signal in pool with state=SIGNAL_CREATED.
    
    Args:
        signal: Layer12Signal from constitution
        
    Returns:
        Confirmation with signal_id
    """
    signal_dict = signal.model_dump()
    signal_dict["state"] = TradeState.SIGNAL_CREATED.value
    signal_dict["created_at"] = datetime.utcnow().isoformat()
    
    signal_pool[signal.signal_id] = signal_dict
    
    logger.info(
        f"L12 signal received: {signal.signal_id} | "
        f"{signal.pair} {signal.direction} @ {signal.entry}"
    )
    
    return {
        "status": "received",
        "signal_id": str(signal.signal_id),
        "state": TradeState.SIGNAL_CREATED.value,
    }


@write_router.post("/risk/calculate", response_model=RiskCalculationResult)
def calculate_risk(request: RiskCalculationRequest) -> RiskCalculationResult:
    """
    Calculate recommended lot size for signal+account.
    
    Args:
        request: RiskCalculationRequest
        
    Returns:
        RiskCalculationResult with lot recommendation
        
    Raises:
        HTTPException: If signal or account not found
    """
    # Get signal
    signal_dict = signal_pool.get(request.signal_id)
    if not signal_dict:
        raise HTTPException(
            status_code=404,
            detail=f"Signal {request.signal_id} not found"
        )
    
    signal = Layer12Signal(**signal_dict)
    
    # Get account
    account_engine = account_registry.get(request.account_id)
    if not account_engine:
        raise HTTPException(
            status_code=404,
            detail=f"Account {request.account_id} not found"
        )
    
    account_state = account_engine.get_state()
    
    # Calculate lot
    result = risk_engine.calculate_lot(
        signal=signal,
        account_state=account_state,
        risk_percent=1.0,  # Default 1% risk (could be from account profile)
        prop_firm_code=account_engine.prop_firm_code,
        risk_mode=request.risk_mode,
        split_ratios=request.split_ratio,
    )
    
    logger.info(
        f"Risk calculated: {request.account_id} | "
        f"Signal={request.signal_id} | "
        f"Lot={result.recommended_lot:.2f} | "
        f"Allowed={result.trade_allowed}"
    )
    
    return result


@write_router.post("/trade/open", status_code=201)
def open_trade(request: TradeOpenRequest) -> Dict:
    """
    Record trade opening.
    
    Validates:
    - Lot <= max_safe_lot from risk calculation
    - Prop firm allows trade
    
    Args:
        request: TradeOpenRequest
        
    Returns:
        Trade record with trade_id
        
    Raises:
        HTTPException: If validation fails
    """
    # Get account
    account_engine = account_registry.get(request.account_id)
    if not account_engine:
        raise HTTPException(
            status_code=404,
            detail=f"Account {request.account_id} not found"
        )
    
    # Get signal to validate lot
    signal_dict = signal_pool.get(request.signal_id)
    if not signal_dict:
        raise HTTPException(
            status_code=404,
            detail=f"Signal {request.signal_id} not found"
        )
    
    signal = Layer12Signal(**signal_dict)
    account_state = account_engine.get_state()
    
    # Re-calculate risk to validate lot
    result = risk_engine.calculate_lot(
        signal=signal,
        account_state=account_state,
        risk_percent=1.0,
        prop_firm_code=account_engine.prop_firm_code,
    )
    
    # Validate trade is allowed
    if not result.trade_allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Trade denied: {result.reason}"
        )
    
    # Validate lot doesn't exceed max safe lot
    if request.lot > result.max_safe_lot:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Lot {request.lot:.2f} exceeds max safe lot "
                f"{result.max_safe_lot:.2f}"
            )
        )
    
    # Calculate risk amount
    sl_distance = abs(request.entry - request.stop_loss)
    pip_value = 10.0  # Simplified
    risk_amount = request.lot * sl_distance * pip_value
    
    # Record trade open
    trade_id = f"TRD-{uuid4().hex[:12]}"
    trade_record = {
        "trade_id": trade_id,
        "account_id": request.account_id,
        "signal_id": str(request.signal_id),
        "source": request.source.value,
        "pair": request.pair,
        "direction": request.direction,
        "entry": request.entry,
        "stop_loss": request.stop_loss,
        "take_profit": request.take_profit,
        "lot": request.lot,
        "risk_amount": risk_amount,
        "state": TradeState.TRADE_OPEN.value,
        "opened_at": datetime.utcnow().isoformat(),
        "closed_at": None,
        "pnl": None,
    }
    
    trade_ledger[trade_id] = trade_record
    
    # Update account state
    account_engine.record_trade_open(risk_amount)
    
    logger.info(
        f"Trade opened: {trade_id} | {request.pair} {request.direction} | "
        f"Lot={request.lot:.2f} | Risk=${risk_amount:.2f}"
    )
    
    return trade_record


@write_router.post("/trade/close")
def close_trade(request: TradeCloseRequest) -> Dict:
    """
    Record trade closure.
    
    Automatically generates J4 reflective journal entry.
    
    Args:
        request: TradeCloseRequest
        
    Returns:
        Updated trade record
        
    Raises:
        HTTPException: If trade not found
    """
    # Get trade
    trade = trade_ledger.get(request.trade_id)
    if not trade:
        raise HTTPException(
            status_code=404,
            detail=f"Trade {request.trade_id} not found"
        )
    
    # Update trade record
    trade["state"] = TradeState.TRADE_CLOSED.value
    trade["closed_at"] = datetime.utcnow().isoformat()
    trade["close_price"] = request.close_price
    trade["pnl"] = request.pnl
    trade["close_reason"] = request.reason
    
    # Update account
    account_id = trade["account_id"]
    account_engine = account_registry.get(account_id)
    if account_engine:
        account_engine.record_trade_close(
            pnl=request.pnl,
            risk_amount=trade["risk_amount"],
        )
    
    # Generate J4 reflective journal
    outcome = TradeOutcome.WIN if request.pnl > 0 else TradeOutcome.LOSS
    
    j4 = ReflectiveJournal(
        timestamp=datetime.utcnow(),
        setup_id=f"{trade['pair']}_{trade['opened_at'][:19]}",
        pair=trade["pair"],
        outcome=outcome,
        did_system_protect=ProtectionAssessment.UNCLEAR,
        discipline_rating=8,
        learning_note=f"Trade closed: {request.reason}",
    )
    
    journal_router.record_reflection(j4)
    
    logger.info(
        f"Trade closed: {request.trade_id} | "
        f"PnL=${request.pnl:.2f} | {request.reason}"
    )
    
    return trade


@write_router.get("/account/{account_id}/state", response_model=AccountState)
def get_account_state(account_id: str) -> AccountState:
    """
    Get current account state for UI gauges.
    
    Args:
        account_id: Account identifier
        
    Returns:
        AccountState snapshot
        
    Raises:
        HTTPException: If account not found
    """
    account_engine = account_registry.get(account_id)
    if not account_engine:
        raise HTTPException(
            status_code=404,
            detail=f"Account {account_id} not found"
        )
    
    return account_engine.get_state()


@write_router.get("/signals")
def get_signals() -> List[Dict]:
    """
    Get active signal pool.
    
    Returns:
        List of active signals
    """
    return list(signal_pool.values())


@write_router.get("/trades")
def get_trades(
    account_id: str = None,
    state: str = None,
) -> List[Dict]:
    """
    Get trade ledger (all trades or filtered).
    
    Args:
        account_id: Optional account filter
        state: Optional state filter
        
    Returns:
        List of trades
    """
    trades = list(trade_ledger.values())
    
    if account_id:
        trades = [t for t in trades if t["account_id"] == account_id]
    
    if state:
        trades = [t for t in trades if t["state"] == state]
    
    return trades


@write_router.get("/trade/{trade_id}")
def get_trade(trade_id: str) -> Dict:
    """
    Get single trade detail.
    
    Args:
        trade_id: Trade identifier
        
    Returns:
        Trade record
        
    Raises:
        HTTPException: If trade not found
    """
    trade = trade_ledger.get(trade_id)
    if not trade:
        raise HTTPException(
            status_code=404,
            detail=f"Trade {trade_id} not found"
        )
    
    return trade


@write_router.post("/account/create", status_code=201)
def create_account(account: AccountCreate) -> Dict:
    """
    Create new account for tracking.
    
    Args:
        account: AccountCreate request
        
    Returns:
        Account info with generated account_id
    """
    account_id = f"ACC-{uuid4().hex[:8]}"
    
    account_engine = AccountEngine.get_or_create(
        account_id=account_id,
        balance=account.balance,
        equity=account.equity,
        prop_firm_code=account.prop_firm_code,
    )
    
    account_registry[account_id] = account_engine
    
    logger.info(
        f"Account created: {account_id} | "
        f"{account.broker} | {account.prop_firm_code}"
    )
    
    return {
        "account_id": account_id,
        "broker": account.broker,
        "account_name": account.account_name,
        "balance": account.balance,
        "prop_firm_code": account.prop_firm_code,
    }
