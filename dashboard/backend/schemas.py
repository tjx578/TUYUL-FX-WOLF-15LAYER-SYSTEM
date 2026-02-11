"""
Dashboard API Schemas - Pydantic V2 Models

Strict type-safe models for the Dashboard API.
All models follow the separation of concerns:
- Layer 12 signals contain NO lot/balance fields
- Dashboard calculates risk and lots
- Prop firm guards validate account state
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

# ========================
# ENUMS
# ========================


class TradeSource(str, Enum):
    """Source of trade execution."""

    EA = "EA"
    MANUAL = "MANUAL"


class RiskMode(str, Enum):
    """Risk calculation mode."""

    FIXED = "FIXED"
    SPLIT = "SPLIT"


class RiskSeverity(str, Enum):
    """Risk assessment severity levels."""

    SAFE = "SAFE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ScalingModel(str, Enum):
    """Risk scaling model based on confidence/DD."""

    FIXED = "FIXED"
    CONFIDENCE = "CONFIDENCE"
    STEP = "STEP"


# ========================
# ACCOUNT MODELS
# ========================


class AccountCreate(BaseModel):
    """Account creation request."""

    broker: str = Field(..., min_length=1, max_length=50)
    account_name: str = Field(..., min_length=1, max_length=100)
    balance: float = Field(..., gt=0, description="Account balance in USD")
    equity: float = Field(..., gt=0, description="Account equity in USD")
    prop_firm_code: str = Field(
        ..., min_length=1, max_length=50, description="ftmo, aqua_instant_pro, etc"
    )
    currency: str = Field(default="USD", max_length=3)

    model_config = ConfigDict(frozen=False)


class AccountState(BaseModel):
    """Current account state snapshot (immutable)."""

    account_id: str = Field(..., description="Account identifier")
    balance: float = Field(..., gt=0)
    equity: float = Field(..., gt=0)
    equity_high: float = Field(..., gt=0, description="Highest equity mark")
    daily_dd_percent: float = Field(..., ge=0, le=100)
    total_dd_percent: float = Field(..., ge=0, le=100)
    open_risk_percent: float = Field(..., ge=0, le=100)
    open_trades: int = Field(..., ge=0)
    risk_state: RiskSeverity = Field(...)

    model_config = ConfigDict(frozen=True)


# ========================
# RISK MODELS
# ========================


class RiskProfile(BaseModel):
    """Risk management profile settings."""

    risk_per_trade_percent: float = Field(
        ..., ge=0.1, le=5.0, description="Risk per trade (0.1-5%)"
    )
    max_daily_risk_percent: float = Field(
        ..., ge=0.1, le=10.0, description="Max daily risk (0.1-10%)"
    )
    max_total_dd_percent: float = Field(..., ge=0.1, le=20.0, description="Max total DD (0.1-20%)")
    max_open_trades: int = Field(..., ge=1, le=10)
    confidence_scaling: bool = Field(default=True, description="Scale risk by confidence")
    scaling_model: ScalingModel = Field(default=ScalingModel.CONFIDENCE)

    model_config = ConfigDict(frozen=False)


# ========================
# LAYER 12 SIGNAL MODEL
# ========================


class Layer12Signal(BaseModel):
    """
    Layer 12 Signal from Constitution.
    NO lot/balance fields - Dashboard calculates these.
    """

    signal_id: UUID = Field(..., description="Unique signal identifier")
    timestamp: datetime = Field(..., description="Signal generation time UTC")
    pair: str = Field(..., min_length=6, max_length=10)
    direction: str = Field(..., pattern="^(BUY|SELL)$")
    entry: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit_1: float = Field(..., gt=0)
    rr: float = Field(..., gt=0, description="Risk/reward ratio")
    verdict: str = Field(..., description="EXECUTE_BUY or EXECUTE_SELL")
    confidence: str = Field(..., description="VERY_HIGH, HIGH, MEDIUM, LOW")
    wolf_score: int = Field(..., ge=0, le=30, description="Wolf 30-point score")
    tii_sym: float = Field(..., ge=0.0, le=1.0, description="Technical integrity index")
    frpc: float = Field(..., ge=0.0, le=1.0, description="Fundamental-risk-prob-context")

    model_config = ConfigDict(frozen=False)

    @field_validator("entry", "stop_loss", "take_profit_1")
    @classmethod
    def validate_prices_positive(cls, v: float) -> float:
        """Ensure all prices are positive."""
        if v <= 0:
            raise ValueError("Price must be positive")
        return v


# ========================
# RISK CALCULATION MODELS
# ========================


class RiskCalculationRequest(BaseModel):
    """Request to calculate lot size for a signal."""

    account_id: str = Field(...)
    signal_id: UUID = Field(...)
    risk_mode: RiskMode = Field(default=RiskMode.FIXED)
    split_ratio: list[float] | None = Field(
        default=None, description="For SPLIT mode: [0.5, 0.3, 0.2] must sum to 1.0"
    )

    model_config = ConfigDict(frozen=False)

    @field_validator("split_ratio")
    @classmethod
    def validate_split_sum(cls, v: list[float] | None) -> list[float] | None:
        """Ensure split ratios sum to 1.0."""
        if v is not None:
            total = sum(v)
            if not (0.99 <= total <= 1.01):  # Allow small float tolerance
                raise ValueError(f"Split ratios must sum to 1.0, got {total}")
        return v


class RiskCalculationResult(BaseModel):
    """Result of lot calculation with prop firm validation."""

    trade_allowed: bool = Field(...)
    recommended_lot: float = Field(..., ge=0)
    max_safe_lot: float = Field(..., ge=0)
    risk_used_percent: float = Field(..., ge=0)
    daily_dd_after: float = Field(..., ge=0)
    total_dd_after: float = Field(..., ge=0)
    severity: RiskSeverity = Field(...)
    reason: str = Field(...)
    split_lots: list[float] | None = Field(default=None, description="For split risk mode")

    model_config = ConfigDict(frozen=True)


# ========================
# TRADE MODELS
# ========================


class TradeOpenRequest(BaseModel):
    """Request to record a trade opening."""

    account_id: str = Field(...)
    signal_id: UUID = Field(...)
    source: TradeSource = Field(...)
    pair: str = Field(..., min_length=6, max_length=10)
    direction: str = Field(..., pattern="^(BUY|SELL)$")
    entry: float = Field(..., gt=0)
    stop_loss: float = Field(..., gt=0)
    take_profit: float = Field(..., gt=0)
    lot: float = Field(..., gt=0)

    model_config = ConfigDict(frozen=False)


class TradeCloseRequest(BaseModel):
    """Request to record a trade closure."""

    trade_id: str = Field(...)
    close_price: float = Field(..., gt=0)
    pnl: float = Field(...)
    reason: str = Field(..., min_length=1, max_length=200)

    model_config = ConfigDict(frozen=False)


# ========================
# PROP FIRM GUARD MODELS
# ========================


class PropFirmGuardResult(BaseModel):
    """Result of prop firm guard validation."""

    allowed: bool = Field(...)
    code: str = Field(..., description="ALLOW, WARN, or DENY code")
    severity: RiskSeverity = Field(...)
    details: str = Field(...)

    model_config = ConfigDict(frozen=True)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "allowed": self.allowed,
            "code": self.code,
            "severity": self.severity.value,
            "details": self.details,
        }
