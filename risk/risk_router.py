"""
Risk Router — Dashboard API Endpoints for Risk Engine v2

Provides REST API for:
- Account risk snapshot
- Signal evaluation
- Risk profile management
- Trade lifecycle tracking
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from loguru import logger

from risk.exceptions import RiskException
from risk.risk_engine_v2 import RiskEngineV2, SignalInput, RiskVerdict
from risk.risk_profile import RiskProfile, RiskMode, save_risk_profile, load_risk_profile

router = APIRouter(prefix="/api/v1/risk")


# ========================
# REQUEST/RESPONSE MODELS
# ========================

class RiskProfileRequest(BaseModel):
    """Request to save risk profile."""
    risk_per_trade: float = Field(..., gt=0, le=5.0, description="Risk % per trade")
    max_daily_dd: float = Field(..., gt=0, le=20.0, description="Max daily drawdown %")
    max_total_dd: float = Field(..., gt=0, le=30.0, description="Max total drawdown %")
    max_open_trades: int = Field(..., ge=1, le=5, description="Max concurrent trades")
    risk_mode: str = Field(..., description="FIXED or SPLIT")
    split_ratio: list[float] = Field(default=[0.4, 0.6], description="SPLIT mode ratio")

    @field_validator("risk_mode")
    @classmethod
    def validate_risk_mode(cls, v: str) -> str:
        if v not in ["FIXED", "SPLIT"]:
            raise ValueError("risk_mode must be FIXED or SPLIT")
        return v


class EvaluateSignalRequest(BaseModel):
    """Request to evaluate a trading signal."""
    symbol: str = Field(..., description="Trading pair")
    direction: str = Field(..., description="BUY or SELL")
    entry_price: float = Field(..., gt=0, description="Entry price")
    stop_loss: float = Field(..., gt=0, description="Stop loss price")
    take_profit_1: float = Field(..., gt=0, description="First take profit")
    rr_ratio: float = Field(..., gt=0, description="Risk/reward ratio")
    trade_id: str = Field(..., description="Unique trade ID")
    sl_distance_2: Optional[float] = Field(None, description="Second SL distance for SPLIT")
    vix_level: Optional[float] = Field(None, description="VIX level")
    session: Optional[str] = Field(None, description="Trading session")
    auto_register: bool = Field(default=False, description="Auto-register if ALLOW")

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        if v not in ["BUY", "SELL"]:
            raise ValueError("direction must be BUY or SELL")
        return v


class CloseTradeRequest(BaseModel):
    """Request to close trade tracking."""
    trade_id: str = Field(..., description="Trade ID")
    entry_number: int = Field(default=1, ge=1, le=2, description="Entry number (1 or 2)")


# ========================
# ENDPOINTS
# ========================

@router.get("/{account_id}/snapshot")
async def get_account_snapshot(
    account_id: str,
    vix_level: Optional[float] = None,
    session: Optional[str] = None,
) -> dict:
    """Get complete account risk snapshot."""
    try:
        engine = RiskEngineV2(account_id)
        snapshot = engine.get_account_snapshot(vix_level=vix_level, session=session)
        return snapshot
    except Exception as exc:
        logger.error("Failed to get account snapshot", account_id=account_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{account_id}/evaluate")
async def evaluate_signal(
    account_id: str,
    req: EvaluateSignalRequest,
) -> dict:
    """
    Evaluate a trading signal against risk constraints.
    
    Returns ALLOW or DENY verdict with lot sizing details.
    Optionally auto-registers the trade if allowed.
    """
    try:
        engine = RiskEngineV2(account_id)
        signal = SignalInput(
            symbol=req.symbol,
            direction=req.direction,
            entry_price=req.entry_price,
            stop_loss=req.stop_loss,
            take_profit_1=req.take_profit_1,
            rr_ratio=req.rr_ratio,
            trade_id=req.trade_id,
            sl_distance_2=req.sl_distance_2,
        )
        
        result = engine.evaluate(signal, vix_level=req.vix_level, session=req.session)
        
        # Auto-register if requested and allowed
        if req.auto_register and result.allowed:
            engine.register_intended_trade(signal, result.lots)
        
        return {
            "verdict": result.verdict.value,
            "deny_code": result.deny_code,
            "lots": result.lots,
            "risk_amount": result.risk_amount,
            "open_risk_after": result.open_risk_after,
            "open_trades_after": result.open_trades_after,
            "details": result.details,
        }
    except RiskException as exc:
        logger.warning("Risk evaluation rejected", account_id=account_id, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to evaluate signal", account_id=account_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{account_id}/profile")
async def save_profile(
    account_id: str,
    req: RiskProfileRequest,
) -> dict:
    """Save risk profile for account."""
    try:
        profile = RiskProfile(
            risk_per_trade=req.risk_per_trade,
            max_daily_dd=req.max_daily_dd,
            max_total_dd=req.max_total_dd,
            max_open_trades=req.max_open_trades,
            risk_mode=RiskMode(req.risk_mode),
            split_ratio=tuple(req.split_ratio),
        )
        save_risk_profile(account_id, profile)
        return {"status": "saved", "profile": profile.to_dict()}
    except RiskException as exc:
        logger.warning("Invalid risk profile", account_id=account_id, error=str(exc))
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to save risk profile", account_id=account_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{account_id}/profile")
async def get_profile(account_id: str) -> dict:
    """Load risk profile for account (returns default if not found)."""
    try:
        profile = load_risk_profile(account_id)
        return profile.to_dict()
    except Exception as exc:
        logger.error("Failed to load risk profile", account_id=account_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{account_id}/close")
async def close_trade(
    account_id: str,
    req: CloseTradeRequest,
) -> dict:
    """Close trade tracking (removes from open exposure)."""
    try:
        engine = RiskEngineV2(account_id)
        engine.close_trade(req.trade_id, req.entry_number)
        return {"status": "closed", "trade_id": req.trade_id, "entry_number": req.entry_number}
    except Exception as exc:
        logger.error("Failed to close trade", account_id=account_id, trade_id=req.trade_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
