"""
Pipeline Contracts — Pydantic models for L12 synthesis validation.

These models define the contract between the analysis pipeline (L1-L11)
and the constitutional verdict engine (L12).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScoresContract(BaseModel):
    """Scoring section of synthesis."""

    wolf_30_point: int = Field(ge=0, le=30)
    f_score: int = Field(ge=0, le=10)
    t_score: int = Field(ge=0, le=12)
    fta_score: float = Field(ge=0.0, le=1.0)
    exec_score: int = Field(ge=0, le=10)


class LayersContract(BaseModel):
    """Layer metrics section of synthesis."""

    L8_tii_sym: float = Field(ge=0.0, le=1.0)
    L8_integrity_index: float = Field(ge=0.0, le=1.0)
    L7_monte_carlo_win: float = Field(ge=0.0, le=1.0)
    conf12: float = Field(ge=0.0, le=1.0)


class ExecutionContract(BaseModel):
    """Execution parameters section of synthesis."""

    direction: str = Field(pattern="^(BUY|SELL|HOLD)$")
    entry_price: float = Field(gt=0.0)
    stop_loss: float = Field(gt=0.0)
    take_profit_1: float = Field(gt=0.0)
    entry_zone: str
    rr_ratio: float = Field(ge=0.0)
    lot_size: float = Field(ge=0.0)
    risk_percent: float = Field(ge=0.0, le=100.0)
    risk_amount: float = Field(ge=0.0)


class RiskContract(BaseModel):
    """Risk management section of synthesis."""

    current_drawdown: float = Field(ge=0.0)


class PropFirmContract(BaseModel):
    """Prop firm compliance section of synthesis."""

    compliant: bool


class BiasContract(BaseModel):
    """Market bias section of synthesis."""

    fundamental: str
    technical: str
    macro: str


class MacroContract(BaseModel):
    """Macro analysis section of synthesis."""

    regime: str
    phase: str = "NEUTRAL"
    volatility_ratio: float = 1.0
    mn_aligned: bool = False
    liquidity: dict[str, Any] = Field(default_factory=dict)
    bias_override: dict[str, Any] = Field(default_factory=dict)


class SystemContract(BaseModel):
    """System metrics section of synthesis."""

    latency_ms: float = Field(ge=0.0)


class SynthesisContract(BaseModel):
    """
    Complete L12 synthesis contract.

    This is the interface between the analysis pipeline (L1-L11)
    and the constitutional verdict engine (L12).
    """

    pair: str
    scores: ScoresContract
    layers: LayersContract | dict[str, Any]  # Allow dict for extra layer data
    execution: ExecutionContract
    risk: RiskContract
    propfirm: PropFirmContract
    bias: BiasContract
    macro: MacroContract
    system: SystemContract

    class Config:
        """Pydantic config."""

        extra = "allow"  # Allow extra fields like macro_vix, _raw_layers, etc.
