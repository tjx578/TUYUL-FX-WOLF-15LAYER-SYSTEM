"""
Trade Domain Models - Pydantic models for manual-first trade flow.

Models:
  - TradeLeg         : Single leg of a trade (entry, SL, TP, lot)
  - Trade            : Complete trade record with status and legs
  - Account          : Account information and risk limits

Enums:
  - TradeStatus      : INTENDED, PENDING, OPEN, CLOSED, CANCELLED, SKIPPED
  - RiskMode         : FIXED, SPLIT
  - CloseReason      : TP_HIT, SL_HIT, MANUAL_CLOSE, etc.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

# ========================
# ENUMS
# ========================


class TradeStatus(StrEnum):
    """Trade lifecycle status"""

    INTENDED = "INTENDED"  # Trader clicked TAKE, dashboard computed lot
    PENDING = "PENDING"  # Order placed at broker (trader confirmed)
    OPEN = "OPEN"  # Price hit entry (auto-detected by price watcher)
    CLOSED = "CLOSED"  # SL/TP hit or manual close
    CANCELLED = "CANCELLED"  # System cancelled (M15 invalid, expiry, news, DD breach)
    SKIPPED = "SKIPPED"  # Trader clicked SKIP


class RiskMode(StrEnum):
    """Risk allocation mode"""

    FIXED = "FIXED"  # Single position, full risk
    SPLIT = "SPLIT"  # Split into multiple legs


class CloseReason(StrEnum):
    """Reason for trade closure"""

    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    MANUAL_CLOSE = "MANUAL_CLOSE"
    SYSTEM_PROTECTION = "SYSTEM_PROTECTION"
    EXPIRY = "EXPIRY"
    NEWS_LOCK = "NEWS_LOCK"
    M15_INVALIDATION = "M15_INVALIDATION"


# ========================
# MODELS
# ========================


class TradeLeg(BaseModel):
    """
    Single leg of a trade.

    For FIXED mode: 1 leg only.
    For SPLIT mode: Multiple legs (e.g., 2-leg or 3-leg).
    """

    leg: int = Field(..., description="Leg number (1, 2, 3, ...)")
    entry: float = Field(..., gt=0, description="Entry price")
    sl: float = Field(..., gt=0, description="Stop loss price")
    tp: float = Field(..., gt=0, description="Take profit price")
    lot: float = Field(..., gt=0, description="Position size in lots")
    status: TradeStatus = Field(..., description="Leg status")


class Trade(BaseModel):
    """
    Complete trade record.

    Represents the full trade lifecycle from INTENDED to final state.
    Dashboard authority: manages state + risk + journal.
    """

    trade_id: str = Field(..., description="Unique trade ID (T-{timestamp})")
    signal_id: str = Field(..., description="Source signal ID (SIG-{pair}_{timestamp})")
    account_id: str = Field(..., description="Account ID (ACC-{id})")
    pair: str = Field(..., description="Trading pair symbol")
    direction: str = Field(..., description="BUY or SELL")
    status: TradeStatus = Field(..., description="Current trade status")
    risk_mode: RiskMode = Field(..., description="Risk allocation mode")
    total_risk_percent: float = Field(..., gt=0, description="Total risk as % of balance")
    total_risk_amount: float = Field(..., gt=0, description="Total risk in account currency")
    legs: list[TradeLeg] = Field(..., description="Trade legs (1 for FIXED, multiple for SPLIT)")
    created_at: datetime = Field(..., description="Trade creation timestamp (UTC)")
    updated_at: datetime = Field(..., description="Last update timestamp (UTC)")
    close_reason: CloseReason | None = Field(
        default=None, description="Reason for closure (if closed)"
    )
    pnl: float | None = Field(
        default=None, description="Profit/loss in account currency (if closed)"
    )

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        """Ensure direction is BUY or SELL"""
        if v.upper() not in ("BUY", "SELL"):
            raise ValueError("Direction must be BUY or SELL")
        return v.upper()

    @field_validator("legs")
    @classmethod
    def validate_legs(cls, v: list[TradeLeg]) -> list[TradeLeg]:
        """Ensure at least one leg exists"""
        if not v:
            raise ValueError("Trade must have at least one leg")
        return v


class Account(BaseModel):
    """
    Account information and risk limits.

    Stores balance, equity, and prop firm constraints.
    Used by dashboard to compute safe lot sizes.
    """

    account_id: str = Field(..., description="Unique account ID (ACC-{id})")
    name: str = Field(..., description="Account name/label")
    balance: float = Field(..., gt=0, description="Account balance")
    equity: float = Field(..., gt=0, description="Account equity (balance + floating P&L)")
    prop_firm: bool = Field(..., description="Is this a prop firm account?")
    max_daily_dd_percent: float = Field(..., gt=0, description="Max daily drawdown %")
    max_total_dd_percent: float = Field(..., gt=0, description="Max total drawdown %")
    max_concurrent_trades: int = Field(..., gt=0, description="Max concurrent trades allowed")

    @field_validator("equity")
    @classmethod
    def validate_equity(cls, v: float, info) -> float:
        """Ensure equity is positive"""
        if v <= 0:
            raise ValueError("Equity must be positive")
        return v


# ========================
# STATE TRANSITION VALIDATION
# ========================

# Valid state transitions (enforce strictly in trade_ledger.py)
VALID_TRANSITIONS = {
    TradeStatus.INTENDED: {TradeStatus.PENDING, TradeStatus.CANCELLED, TradeStatus.SKIPPED},
    TradeStatus.PENDING: {TradeStatus.OPEN, TradeStatus.CANCELLED},
    TradeStatus.OPEN: {TradeStatus.CLOSED},
    # Terminal states (no transitions allowed)
    TradeStatus.CLOSED: set(),
    TradeStatus.CANCELLED: set(),
    TradeStatus.SKIPPED: set(),
}


def is_valid_transition(current: TradeStatus, new: TradeStatus) -> bool:
    """
    Check if state transition is valid.

    Args:
        current: Current trade status
        new: New trade status

    Returns:
        True if transition is allowed, False otherwise
    """
    return new in VALID_TRANSITIONS.get(current, set())
