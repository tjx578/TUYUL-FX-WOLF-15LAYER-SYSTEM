"""
Journal Schema — Pydantic models for J1–J4 decision records.

Models:
  - ContextJournal (J1)     : Market context at analysis time
  - DecisionJournal (J2)    : Full decision record (all verdicts)
  - ExecutionJournal (J3)   : Execution details (EXECUTE_* only)
  - ReflectiveJournal (J4)  : Post-trade reflection

Enums:
  - VerdictType             : EXECUTE_BUY, EXECUTE_SELL, HOLD, NO_TRADE
  - TradeOutcome            : WIN, LOSS, BREAKEVEN, SKIPPED, EXPIRED, CANCELLED
  - ProtectionAssessment    : YES, NO, UNCLEAR
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ========================
# ENUMS
# ========================

class VerdictType(str, Enum):
    """L12 Verdict Types"""
    EXECUTE_BUY = "EXECUTE_BUY"
    EXECUTE_SELL = "EXECUTE_SELL"
    HOLD = "HOLD"
    NO_TRADE = "NO_TRADE"


class TradeOutcome(str, Enum):
    """Post-trade outcome classification"""
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    SKIPPED = "SKIPPED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ProtectionAssessment(str, Enum):
    """Did system protect trader from bad setup?"""
    YES = "YES"
    NO = "NO"
    UNCLEAR = "UNCLEAR"


# ========================
# J1: CONTEXT JOURNAL
# ========================

class ContextJournal(BaseModel):
    """
    J1 — Market context snapshot at analysis time.
    Source: context/live_context_bus.py, analysis/L1, L2, L3
    """
    timestamp: datetime = Field(..., description="Analysis timestamp (UTC)")
    pair: str = Field(..., description="Trading pair symbol")
    session: str = Field(..., description="Trading session (ASIA/LONDON/NEW_YORK)")
    market_regime: str = Field(..., description="Trending/ranging/consolidation")
    news_lock: bool = Field(..., description="Is news lock active?")
    context_coherence: float = Field(..., ge=0.0, le=1.0, description="Context alignment score")
    mta_alignment: bool = Field(..., description="Multi-timeframe alignment")
    technical_bias: str = Field(..., description="BULLISH/BEARISH/NEUTRAL")


# ========================
# J2: DECISION JOURNAL
# ========================

class DecisionJournal(BaseModel):
    """
    J2 — Full decision record for EVERY verdict.
    Source: constitution/verdict_engine.py output
    """
    timestamp: datetime = Field(..., description="Decision timestamp (UTC)")
    pair: str = Field(..., description="Trading pair symbol")
    setup_id: str = Field(..., description="Unique setup ID (pair_timestamp)")
    
    # Scores (0-30 scale for wolf, 0-10 for others)
    wolf_30_score: int = Field(..., ge=0, le=30, description="Wolf 30-point score")
    f_score: int = Field(..., ge=0, le=10, description="Fundamental score")
    t_score: int = Field(..., ge=0, le=10, description="Technical score")
    fta_score: int = Field(..., ge=0, le=10, description="FTA combined score")
    exec_score: int = Field(..., ge=0, le=10, description="Execution score")
    
    # Integrity metrics (0-1 scale)
    tii_sym: float = Field(..., ge=0.0, le=1.0, description="Technical integrity index")
    integrity_index: float = Field(..., ge=0.0, le=1.0, description="Overall integrity")
    monte_carlo_win: float = Field(..., ge=0.0, le=1.0, description="Monte Carlo win probability")
    conf12: float = Field(..., ge=0.0, le=1.0, description="L12 confidence score")
    
    # Verdict
    verdict: VerdictType = Field(..., description="Final L12 verdict")
    confidence: str = Field(..., description="Confidence level (VERY_HIGH/HIGH/MEDIUM/LOW)")
    wolf_status: str = Field(..., description="Wolf status (ALPHA/PACK/SCOUT/NO_HUNT)")
    
    # Gate results
    gates_passed: int = Field(..., ge=0, le=9, description="Number of gates passed")
    gates_total: int = Field(default=9, description="Total number of gates")
    failed_gates: List[str] = Field(default_factory=list, description="List of failed gate names")
    violations: List[str] = Field(default_factory=list, description="Constitutional violations")
    primary_rejection_reason: Optional[str] = Field(default=None, description="Main reason for rejection")
    
    @field_validator("setup_id")
    @classmethod
    def validate_setup_id(cls, v: str) -> str:
        """Ensure setup_id follows format: {pair}_{timestamp}"""
        if "_" not in v:
            raise ValueError("setup_id must contain underscore separator (pair_timestamp)")
        return v


# ========================
# J3: EXECUTION JOURNAL
# ========================

class ExecutionJournal(BaseModel):
    """
    J3 — Execution details (only for EXECUTE_* verdicts).
    Source: execution/state_machine.py, execution/pending_engine.py
    """
    timestamp: datetime = Field(..., description="Execution timestamp (UTC)")
    setup_id: str = Field(..., description="Reference to J2 setup_id")
    pair: str = Field(..., description="Trading pair symbol")
    direction: str = Field(..., description="BUY or SELL")
    
    # Order details
    entry_price: float = Field(..., gt=0, description="Entry price")
    stop_loss: float = Field(..., gt=0, description="Stop loss price")
    take_profit_1: float = Field(..., gt=0, description="First take profit target")
    rr_ratio: float = Field(..., gt=0, description="Risk/reward ratio")
    risk_percent: float = Field(..., gt=0, description="Risk as % of balance")
    lot_size: float = Field(..., gt=0, description="Position size in lots")
    
    # Execution config
    execution_mode: str = Field(default="TP1_ONLY", description="Execution mode")
    order_type: str = Field(default="PENDING_ONLY", description="Order type")
    sm_state: str = Field(..., description="State machine state")
    
    @field_validator("setup_id")
    @classmethod
    def validate_setup_id(cls, v: str) -> str:
        """Ensure setup_id follows format: {pair}_{timestamp}"""
        if "_" not in v:
            raise ValueError("setup_id must contain underscore separator (pair_timestamp)")
        return v


# ========================
# J4: REFLECTIVE JOURNAL
# ========================

class ReflectiveJournal(BaseModel):
    """
    J4 — Post-trade or post-reject reflection.
    Manual entry or automated post-mortem analysis.
    """
    timestamp: datetime = Field(..., description="Reflection timestamp (UTC)")
    setup_id: str = Field(..., description="Reference to J2 setup_id")
    pair: str = Field(..., description="Trading pair symbol")
    
    # Outcome assessment
    outcome: TradeOutcome = Field(..., description="Trade outcome classification")
    did_system_protect: ProtectionAssessment = Field(..., description="Protection assessment")
    was_rejection_correct: Optional[bool] = Field(default=None, description="Was rejection correct?")
    
    # Discipline and learning
    discipline_rating: int = Field(..., ge=1, le=10, description="Discipline score (1-10)")
    override_attempted: bool = Field(default=False, description="Was override attempted?")
    learning_note: str = Field(default="", description="Key learning from this trade")
    system_adjustment_candidate: bool = Field(default=False, description="Should system be adjusted?")
    
    @field_validator("setup_id")
    @classmethod
    def validate_setup_id(cls, v: str) -> str:
        """Ensure setup_id follows format: {pair}_{timestamp}"""
        if "_" not in v:
            raise ValueError("setup_id must contain underscore separator (pair_timestamp)")
        return v
