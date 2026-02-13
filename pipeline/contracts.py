"""
Pipeline Contracts v7.4r∞ — Pydantic models for L12 synthesis validation.

These models define the contract between the analysis pipeline (L1-L11)
and the constitutional verdict engine (L12).

Full v7.4r∞ schema: 4 Core Modules × 15 Layers × Complete Pipeline.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScoresContract(BaseModel):
    """Scoring section of synthesis (v7.4r∞ — Wolf 30-Point)."""

    wolf_30_point: int = Field(ge=0, le=30)
    f_score: int = Field(ge=0, le=7)
    t_score: int = Field(ge=0, le=13)
    fta_score: float = Field(ge=0.0, le=1.0)
    fta_multiplier: float = Field(ge=0.0, default=1.0)
    exec_score: int = Field(ge=0, le=6)
    psychology_score: int = Field(ge=0, le=100, default=0)
    technical_score: int = Field(ge=0, le=100, default=0)


class LayersContract(BaseModel):
    """Layer metrics section of synthesis (v7.4r∞)."""

    L1_context_coherence: float = Field(ge=0.0, le=1.0, default=0.0)
    L2_reflex_coherence: float = Field(ge=0.0, le=1.0, default=0.0)
    L3_trq3d_energy: float = Field(ge=0.0, le=1.0, default=0.0)
    L7_monte_carlo_win: float = Field(ge=0.0, le=1.0, default=0.0)
    L8_tii_sym: float = Field(ge=0.0, le=1.0)
    L8_integrity_index: float = Field(ge=0.0, le=1.0)
    L9_dvg_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    L9_liquidity_score: float = Field(ge=0.0, le=1.0, default=0.0)
    conf12: float = Field(ge=0.0, le=1.0)


class ExecutionContract(BaseModel):
    """Execution parameters section of synthesis (v7.4r∞)."""

    direction: str = Field(pattern="^(BUY|SELL|HOLD)$")
    entry_price: float = Field(ge=0.0)
    stop_loss: float = Field(ge=0.0)
    take_profit_1: float = Field(ge=0.0)
    entry_zone: str = ""
    execution_mode: str = "TP1_ONLY"
    battle_strategy: str = "SHADOW_STRIKE"
    rr_ratio: float = Field(ge=0.0)
    lot_size: float = Field(ge=0.0)
    risk_percent: float = Field(ge=0.0, le=100.0)
    risk_amount: float = Field(ge=0.0)
    slippage_estimate: float = Field(ge=0.0, default=0.0)
    optimal_timing: str = ""


class RiskContract(BaseModel):
    """Risk management section of synthesis (v7.4r∞)."""

    current_drawdown: float = Field(ge=0.0)
    drawdown_level: str = "LEVEL_0"
    risk_multiplier: float = Field(ge=0.0, default=1.0)
    risk_status: str = "ACCEPTABLE"
    lrce: float = Field(ge=0.0, le=1.0, default=0.0)


class PropFirmContract(BaseModel):
    """Prop firm compliance section of synthesis (v7.4r∞)."""

    compliant: bool
    daily_loss_status: str = "OK"
    max_drawdown_status: str = "OK"
    profit_target_progress: float = Field(ge=0.0, default=0.0)


class BiasContract(BaseModel):
    """Market bias section of synthesis."""

    fundamental: str
    technical: str
    macro: str


class CognitiveContract(BaseModel):
    """Cognitive section (v7.4r∞ — from core_cognitive_unified.py)."""

    regime: str = "TREND"
    dominant_force: str = "NEUTRAL"
    cbv: float = 0.0
    csi: float = 0.0


class FusionFRPCContract(BaseModel):
    """Fusion/FRPC section (v7.4r∞ — from core_fusion_unified.py)."""

    conf12: float = Field(ge=0.0, le=1.0, default=0.0)
    frpc_energy: float = 0.0
    lambda_esi: float = 0.003
    integrity: float = Field(ge=0.0, le=1.0, default=0.0)


class TRQ3DContract(BaseModel):
    """TRQ-3D section (v7.4r∞ — from core_quantum_unified.py)."""

    alpha: float = 0.0
    beta: float = 0.0
    gamma: float = 0.0
    drift: float = 0.0
    mean_energy: float = 0.0
    intensity: float = 0.0


class SMCContract(BaseModel):
    """SMC section (v7.4r∞ — from core_cognitive + core_fusion)."""

    structure: str = "RANGE"
    smart_money_signal: str = "NEUTRAL"
    liquidity_zone: str = "0.00000"
    ob_present: bool = False
    fvg_present: bool = False
    sweep_detected: bool = False
    bias: str = "NEUTRAL"


class WolfDisciplineContract(BaseModel):
    """Wolf discipline section (v7.4r∞ — from core_reflective_unified.py)."""

    score: float = Field(ge=0.0, le=1.0, default=0.0)
    polarity_deviation: float = 0.0
    lambda_balance: str = "ACTIVE"
    bias_symmetry: str = "NEUTRAL"
    eaf_score: float = Field(ge=0.0, le=1.0, default=0.0)
    emotional_state: str = "CALM"


class GatesContract(BaseModel):
    """9-Gate Constitutional Check (v7.4r∞)."""

    total_passed: int = Field(ge=0, le=9, default=0)
    total_gates: int = 9
    gate_1_tii: str = "FAIL"
    gate_2_montecarlo: str = "FAIL"
    gate_3_frpc: str = "FAIL"
    gate_4_conf12: str = "FAIL"
    gate_5_rr: str = "FAIL"
    gate_6_integrity: str = "FAIL"
    gate_7_propfirm: str = "FAIL"
    gate_8_drawdown: str = "FAIL"
    gate_9_latency: str = "FAIL"


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
    Complete L12 synthesis contract (v7.4r∞).

    This is the interface between the analysis pipeline (L1-L11)
    and the constitutional verdict engine (L12).
    """

    pair: str
    scores: ScoresContract
    layers: LayersContract | dict[str, Any]
    execution: ExecutionContract
    risk: RiskContract
    propfirm: PropFirmContract
    bias: BiasContract
    cognitive: CognitiveContract = Field(default_factory=CognitiveContract)
    fusion_frpc: FusionFRPCContract = Field(default_factory=FusionFRPCContract)
    trq3d: TRQ3DContract = Field(default_factory=TRQ3DContract)
    smc: SMCContract = Field(default_factory=SMCContract)
    wolf_discipline: WolfDisciplineContract = Field(default_factory=WolfDisciplineContract)
    macro: MacroContract
    system: SystemContract

    class Config:
        """Pydantic config."""

        extra = "allow"  # Allow extra fields like macro_vix, _raw_layers, etc.
