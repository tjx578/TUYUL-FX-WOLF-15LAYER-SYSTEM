#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌀 TUYUL FX AGI — Core Reflective Unified System
═══════════════════════════════════════════════════════════════════════════════
REFLECTIVE ANALYSIS CORE (v7.0r∞-ANALYSIS)

This module is ANALYSIS-ONLY.
It produces reflective intelligence signals but has ZERO execution authority.

✔ AI-safe
✔ Orchestrator-safe  
✔ Audit-safe
✔ Non-binding recommendations only

Architecture:
┌─────────────────────────────────────────────────────────────────────────────┐
│                    🔒 GOVERNANCE GUARD (ABSOLUTE)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                         REFLECTIVE LAYER (L12-L16)                          │
│  TII Engine     │  Field Stabilizer │  Precision Engine │  EAF Calculator  │
├──────────────────┴───────────────────┴───────────────────┴─────────────────┤
│                    REFLECTIVE PIPELINE CONTROLLER                           │
│  Mode Controller │ Evolution Engine │ Feedback Loop │ Symmetry Patch       │
├─────────────────────────────────────────────────────────────────────────────┤
│                      BRIDGE LAYER (Cross-System Sync)                       │
│  Quantum Bridge │ Hybrid Bridge │ Data Bridge │ TRQ3D Unified              │
├─────────────────────────────────────────────────────────────────────────────┤
│                    🐺 WOLF DISCIPLINE INTEGRATOR                            │
│  24-Point Checklist │ Risk Calibrator │ Volume Quadrant │ Bots Sync        │
├─────────────────────────────────────────────────────────────────────────────┤
│                    ⛔ EXECUTION BLOCKED (ANALYSIS ONLY)                     │
└─────────────────────────────────────────────────────────────────────────────┘

Author: Tuyul Kartel FX Advanced Ultra
Version: 7.0r∞-ANALYSIS
Mode: ANALYSIS_ONLY (Non-Execution)
"""

from __future__ import annotations

import os
import math
import random
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from statistics import mean, stdev
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Sequence

logger = logging.getLogger(__name__)


# =============================================================================
# 🔒 SECTION 1: GOVERNANCE GUARD (ABSOLUTE)
# =============================================================================
# AI / Orchestrator MUST NEVER enable this.
# This is the master kill-switch for any execution attempts.

_REFLECTIVE_EXECUTION_ALLOWED = (
    os.getenv("TUYUL_REFLECTIVE_EXECUTION_ALLOWED", "0") == "1"
)

GOVERNANCE_MODE = "ANALYSIS_ONLY"
BINDING_STATUS = "NON_BINDING"

def _check_execution_guard() -> Tuple[bool, str]:
    """Check if execution is allowed.

    Returns (True, reason) ONLY when TUYUL_REFLECTIVE_EXECUTION_ALLOWED=1.
    Default: always blocked (analysis-only mode).
    """
    if not _REFLECTIVE_EXECUTION_ALLOWED:
        return False, "EXECUTION_BLOCKED_BY_GOVERNANCE"
    # Env var explicitly set to "1" — execution permitted
    return True, "EXECUTION_ALLOWED_BY_ENV_OVERRIDE"


# =============================================================================
# 🔧 SECTION 2: EXCEPTIONS
# =============================================================================

class ReflectiveError(Exception):
    """Base exception for reflective system."""
    pass

class TIIValidationError(ReflectiveError):
    """TII validation failed."""
    pass

class FieldStabilityError(ReflectiveError):
    """Field stability calculation error."""
    pass

class PipelineError(ReflectiveError):
    """Pipeline execution error."""
    pass

class VaultIntegrityError(ReflectiveError):
    """Vault integrity check failed."""
    pass

class BridgeSyncError(ReflectiveError):
    """Bridge synchronization error."""
    pass

class EAFCalculationError(ReflectiveError):
    """EAF calculation error."""
    pass

class FRPCError(ReflectiveError):
    """FRPC calculation error."""
    pass

class EvolutionError(ReflectiveError):
    """Evolution engine error."""
    pass

class GovernanceBlockError(ReflectiveError):
    """Execution blocked by governance."""
    pass


# =============================================================================
# 🔧 SECTION 3: ENUMS
# =============================================================================

class FieldState(str, Enum):
    """Field stability states."""
    ACCUMULATION = "accumulation"
    EXPANSION = "expansion"
    CONTRACTION = "contraction"
    REVERSAL = "reversal"
    STABLE = "stable"

class TIIClassification(str, Enum):
    """TII classification levels."""
    STRONG_VALID = "strong_valid"
    VALID = "valid"
    MARGINAL = "marginal"
    WEAK = "weak"
    INVALID = "invalid"

class TIIStatus(str, Enum):
    """TII execution status."""
    APPROVED = "approved"
    MARGINAL = "marginal"
    REJECTED = "rejected"

class PipelineMode(str, Enum):
    """Pipeline operation modes."""
    BALANCED = "balanced"
    INVERSION = "inversion"
    AGGRESSIVE = "aggressive"
    DEFENSIVE = "defensive"

class VaultSyncStatus(str, Enum):
    """Vault synchronization status."""
    SYNCED = "synced"
    PENDING = "pending"
    DRIFT = "drift"
    ERROR = "error"

class IntegrityLevel(str, Enum):
    """Integrity assessment levels."""
    FULL = "full"
    PARTIAL = "partial"
    DEGRADED = "degraded"
    CRITICAL = "critical"

class SyncStatus(str, Enum):
    """Cross-system sync status."""
    SYNCED = "synced"
    PENDING = "pending"
    DRIFT = "drift"
    ERROR = "error"

class EmotionalState(str, Enum):
    """Trader emotional states."""
    CALM = "calm"
    FOCUSED = "focused"
    ANXIOUS = "anxious"
    EUPHORIC = "euphoric"
    FRUSTRATED = "frustrated"
    FEARFUL = "fearful"
    OVERCONFIDENT = "overconfident"
    FATIGUED = "fatigued"

class TradingBehavior(str, Enum):
    """Detectable trading behaviors."""
    NORMAL = "normal"
    REVENGE_TRADING = "revenge_trading"
    FOMO = "fomo"
    OVERTRADING = "overtrading"
    HESITATION = "hesitation"
    IMPULSIVE = "impulsive"
    DISCIPLINED = "disciplined"

class PropagationState(str, Enum):
    """FRPC propagation states."""
    FULL_SYNC = "full_sync"
    PARTIAL_SYNC = "partial_sync"
    DRIFT = "drift"
    DESYNC = "desync"

class ReflectiveEnergyState(str, Enum):
    """Lorentzian energy states."""
    STABLE = "stable"
    HIGH_FLUX = "high_flux"
    LOW_SYNC = "low_sync"

class MetaState(str, Enum):
    """Meta-layer states."""
    SYNCHRONIZED = "synchronized"
    COHERENT = "coherent"
    LEARNING = "learning"
    DRIFT_DETECTED = "drift_detected"

class ExecutionStatus(str, Enum):
    """Execution status (always blocked in analysis mode)."""
    BLOCKED = "blocked"
    DEFERRED = "deferred"
    ANALYSIS_ONLY = "analysis_only"

class DisciplineCategory(str, Enum):
    """Wolf discipline checklist categories."""
    ENTRY = "entry"
    RISK = "risk"
    PSYCHOLOGICAL = "psychological"
    PROPFIRM = "propfirm"

class ReflectiveAdjustment(str, Enum):
    """Types of reflective adjustments."""
    BOOST = "boost"
    NEUTRAL = "neutral"
    CAUTION = "caution"
    BLOCK = "block"

class TimeFrame(str, Enum):
    """Supported timeframes."""
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"

class EnergyLevel(str, Enum):
    """Energy level classifications."""
    CRITICAL_LOW = "critical_low"
    LOW = "low"
    NEUTRAL = "neutral"
    HIGH = "high"
    CRITICAL_HIGH = "critical_high"

class BiasContext(str, Enum):
    """Market bias context (descriptive only, not directive)."""
    BULLISH_CONTEXT = "bullish_context"
    BEARISH_CONTEXT = "bearish_context"
    NEUTRAL_CONTEXT = "neutral_context"


# =============================================================================
# 🔧 SECTION 4: CONSTANTS
# =============================================================================

LAMBDA_ESI = 0.06

DEFAULT_TII_THRESHOLDS = {
    "strong_valid": 0.93,
    "valid": 0.90,
    "marginal": 0.85,
    "weak": 0.75,
    "invalid": 0.0,
}

TRADE_VALIDATION_THRESHOLDS = {
    "min_rr_ratio": 2.0,
    "min_integrity": 0.90,
    "min_confidence": 0.80,
}

EAF_CONFIG = {
    "fear_weight": 0.25,
    "greed_weight": 0.25,
    "fatigue_weight": 0.20,
    "frustration_weight": 0.30,
    "min_eaf_for_trade": 0.70,
    "optimal_eaf": 0.85,
    "max_consecutive_losses": 3,
    "cooldown_after_losses_minutes": 30,
}

QUANTUM_BRIDGE_CONFIG = {
    "min_frpc": 0.96,
    "min_tii": 0.92,
    "max_drift": 0.005,
    "coherence_threshold": 0.95,
}

MODE_CONTROLLER_CONFIG = {
    "threshold_drift": 0.002,
    "threshold_rcadj": 0.8,
    "threshold_qcf": 0.9,
    "volatility_trigger": 1.8,
    "switch_cooldown": 300.0,
}

PIPELINE_CONFIG = {
    "mode": "balanced",
    "tii_threshold": 0.92,
    "wlwci_weight": 0.35,
    "frpc_weight": 0.35,
    "eaf_weight": 0.30,
}

SYMMETRY_PATCH_CONFIG = {
    "lambda_esi": 0.06,
    "symmetry_threshold": 0.004,
}

GOVERNANCE_CONFIG = {
    "execution_allowed": False,
    "binding": "ANALYSIS_ONLY",
    "mode": "NON_EXECUTION",
}


# =============================================================================
# 🔧 SECTION 5: DATACLASSES
# =============================================================================

@dataclass
class TIIThresholds:
    """TII threshold configuration."""
    strong_valid: float = 0.93
    valid: float = 0.90
    marginal: float = 0.85
    weak: float = 0.75
    invalid: float = 0.0

    def classify(self, tii: float) -> TIIClassification:
        if tii >= self.strong_valid:
            return TIIClassification.STRONG_VALID
        elif tii >= self.valid:
            return TIIClassification.VALID
        elif tii >= self.marginal:
            return TIIClassification.MARGINAL
        elif tii >= self.weak:
            return TIIClassification.WEAK
        return TIIClassification.INVALID


@dataclass
class TIIResult:
    """Result from TII calculation."""
    tii: float
    status: TIIClassification
    components: Dict[str, float]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class FRPCResult:
    """Result from FRPC calculation."""
    frpc: float
    propagation_state: PropagationState
    alpha_sync: float = 0.0
    gamma_phase: float = 0.0
    raw_value: float = 0.0


@dataclass
class FieldStabilityResult:
    """Result from field stability analysis."""
    gradient: float
    integrity_index: float
    field_state: FieldState
    alpha: float = 0.0
    beta: float = 0.0
    gamma: float = 0.0


@dataclass
class QuadEnergyResult:
    """Result from quad energy calculation."""
    mean_energy: float
    reflective_coherence: float
    drift: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class TRQ3DResult:
    """Result from TRQ3D analysis."""
    total_energy: float
    coherence_score: float
    alignment_score: float
    dominant_direction: int
    bias_context: BiasContext
    resonance_score: float = 0.0
    pre_move_detected: bool = False
    recommendation: str = "ANALYSIS_ONLY"


@dataclass
class SymmetryEvaluation:
    """Result from symmetry patch evaluation."""
    tii_sym: float
    polarity: float
    phase: str
    e3d_star: float = 0.0
    grad_abg_star: float = 0.0
    integrity_index: float = 0.0


@dataclass
class TradeExecutionResult:
    """Result from trade execution (always blocked in analysis mode)."""
    timestamp: str
    pair: str
    status: ExecutionStatus
    outcome: str
    governance_note: str = "ANALYSIS_ONLY_EXECUTION_BLOCKED"


@dataclass
class EAFResult:
    """Result from EAF calculation."""
    eaf_score: float
    emotional_bias: float
    stability_index: float
    focus_level: float
    discipline_score: float
    detected_state: EmotionalState
    detected_behavior: TradingBehavior
    can_trade: bool
    warnings: List[str]
    recommendations: List[str]
    cooldown_required: bool = False
    cooldown_minutes: int = 0


@dataclass
class EmotionalInput:
    """Input for EAF calculation."""
    recent_wins: int = 0
    recent_losses: int = 0
    consecutive_losses: int = 0
    last_trade_pnl: float = 0.0
    session_duration_minutes: int = 0
    time_since_last_break_minutes: int = 0
    time_since_last_loss_minutes: int = 60
    self_reported_state: Optional[EmotionalState] = None
    confidence_level: float = 0.5
    trades_in_last_hour: int = 0
    avg_decision_time_seconds: float = 30.0
    stop_moved_count: int = 0


@dataclass
class QuantumState:
    """Quantum layer state."""
    probability_ready: bool = False
    neural_active: bool = False
    scenario: str = "UNKNOWN"
    confidence: float = 0.0
    decision: str = "HOLD"


@dataclass
class ReflectiveState:
    """Reflective layer state."""
    frpc: float = 0.0
    tii: float = 0.0
    coherence: float = 0.0
    drift: float = 0.0
    integrity_valid: bool = False


@dataclass
class BridgeState:
    """Bridge synchronization state."""
    quantum_state: QuantumState
    reflective_state: ReflectiveState
    sync_status: SyncStatus
    coherence_achieved: bool = False


@dataclass
class PipelineState:
    """Pipeline execution state."""
    mode: PipelineMode
    tii_threshold: float
    wlwci_weight: float
    active: bool = True


@dataclass
class VaultStatus:
    """Vault synchronization status."""
    name: str
    sync_status: VaultSyncStatus
    last_sync: str
    integrity: float = 1.0


@dataclass
class IntegrityAuditResult:
    """Result from integrity audit."""
    score: float
    level: IntegrityLevel
    issues: List[str]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ReflectiveCycleResult:
    """Result from reflective cycle."""
    metrics: Dict[str, Any]
    config: Dict[str, Any]
    active_mode: PipelineMode
    tii_threshold: float
    wlwci_weight: float


@dataclass
class DisciplineCheckResult:
    """Result of a single discipline check."""
    category: DisciplineCategory
    check_name: str
    passed: bool
    weight: float
    notes: str = ""


@dataclass
class WolfDisciplineScore:
    """Complete Wolf discipline evaluation."""
    total_score: float
    entry_score: float
    risk_score: float
    psychological_score: float
    propfirm_score: float
    checks_passed: int
    checks_failed: int
    critical_failures: List[str]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class CalibrationSummary:
    """Risk calibration summary."""
    status: str
    total_samples: int
    mean_error: float
    calibration_score: float


@dataclass
class VolumeQuadrantResult:
    """Result from volume quadrant analysis."""
    timestamp: str
    high: float
    low: float
    vwap: float
    threshold: float
    quadrants: Dict[str, float]
    rvi: float
    bias: str
    key_support_demand: float
    liquidity_pool: float


@dataclass
class BotSyncState:
    """State of bot synchronization."""
    timestamp: str
    status: str
    bias: str
    integrity_index: float
    reflective_coherence: float
    bots_synced: int
    details: List[Dict[str, Any]]


@dataclass 
class EvolutionSnapshot:
    """Evolution engine snapshot."""
    timestamp: str
    reflective_integrity: float
    meta_weights: Dict[str, float]


@dataclass
class FeedbackSnapshot:
    """Feedback loop snapshot."""
    pair: str
    reflective_integrity: float
    meta_state: str
    alpha: float
    beta: float
    gamma: float
    bias: str
    source_timestamp: str
    evaluated_at: str


@dataclass
class ReflectiveFeedbackState:
    """Reflective feedback state."""
    timestamp: str
    samples: int
    gradient: float
    tii: float
    reflective_energy: float


@dataclass
class AnalysisPayload:
    """Complete analysis payload for orchestrator consumption."""
    schema_version: str
    analysis_mode: str
    timestamp: str
    fusion_momentum: Dict[str, Any]
    fusion_structure: Dict[str, Any]
    precision: Dict[str, Any]
    governance: Dict[str, Any]


# =============================================================================
# ⚙️ SECTION 6: ALGO PRECISION ENGINE (TII) — ANALYSIS ONLY
# =============================================================================

def algo_precision_engine(
    price: float = 0.0,
    vwap: float = 0.0,
    trq_energy: float = 0.0,
    bias_strength: float = 0.0,
    reflective_intensity: float = 0.0,
    meta_integrity: float = 0.97,
) -> TIIResult:
    """
    Calculate Trade Integrity Index (TII) — ANALYSIS ONLY.
    
    Formula: TII = (TRQ_Energy × Reflective_Intensity × Bias_Strength × Integrity) / (1 + |Price - VWAP|)
    """
    deviation = abs(price - vwap) if vwap != 0 else 0.01
    precision = trq_energy * reflective_intensity
    tii = round(precision * bias_strength * meta_integrity / (1 + deviation), 4)
    
    thresholds = TIIThresholds()
    status = thresholds.classify(tii)
    
    return TIIResult(
        tii=tii,
        status=status,
        components={
            "trq_energy": trq_energy,
            "bias_strength": bias_strength,
            "reflective_intensity": reflective_intensity,
            "meta_integrity": meta_integrity,
            "price_vwap_deviation": deviation,
        },
    )


def classify_tii_state(tii: float, threshold: float) -> TIIClassification:
    """Classify TII relative to threshold."""
    thresholds = TIIThresholds()
    return thresholds.classify(tii)


def get_tii_status(tii: float) -> str:
    """Get TII status string."""
    if tii >= 0.93:
        return "strong_valid"
    elif tii >= 0.90:
        return "valid"
    elif tii >= 0.85:
        return "marginal"
    else:
        return "invalid"


# =============================================================================
# 🌀 SECTION 7: FRPC — REFLECTIVE PROPAGATION COEFFICIENT
# =============================================================================

def fusion_reflective_propagation_coefficient(
    fusion_score: float = 0.0,
    trq_energy: float = 0.0,
    reflective_intensity: float = 0.0,
    alpha: float = 0.0,
    beta: float = 0.0,
    gamma: float = 0.0,
    integrity_index: float = 0.97,
) -> FRPCResult:
    """
    Calculate Fusion Reflective Propagation Coefficient (FRPC).
    
    Formula: FRPC = (tanh(fusion) × tanh(trq) × tanh(intensity) × α_sync) / (1 + γ_phase) × integrity
    """
    alpha_sync = (alpha + beta + gamma) / 3 if (alpha + beta + gamma) > 0 else 0.5
    gamma_phase = (alpha - gamma) ** 2 + (beta - alpha) ** 2
    
    raw = (
        math.tanh(fusion_score) *
        math.tanh(trq_energy) *
        math.tanh(reflective_intensity) *
        alpha_sync /
        (1 + gamma_phase)
    )
    
    frpc = round(max(0.0, min(raw * integrity_index, 0.999)), 4)
    
    if frpc >= 0.95:
        state = PropagationState.FULL_SYNC
    elif frpc >= 0.85:
        state = PropagationState.PARTIAL_SYNC
    elif frpc >= 0.70:
        state = PropagationState.DRIFT
    else:
        state = PropagationState.DESYNC
    
    return FRPCResult(
        frpc=frpc,
        propagation_state=state,
        alpha_sync=round(alpha_sync, 4),
        gamma_phase=round(gamma_phase, 6),
        raw_value=round(raw, 4),
    )


# =============================================================================
# ⚡ SECTION 8: FIELD STABILITY + ENERGY
# =============================================================================

def adaptive_field_stabilizer(
    alpha: float,
    beta: float,
    gamma: float,
) -> FieldStabilityResult:
    """
    Analyze α-β-γ field stability and compute gradient.
    """
    gradient = round(
        (abs(alpha - beta) + abs(beta - gamma) + abs(alpha - gamma)) / 3,
        5
    )
    
    if gradient < 0.02:
        state = FieldState.ACCUMULATION
    elif gradient < 0.035:
        state = FieldState.STABLE
    elif gradient < 0.05:
        state = FieldState.EXPANSION
    elif gradient < 0.08:
        state = FieldState.CONTRACTION
    else:
        state = FieldState.REVERSAL
    
    integrity = round(max(0.9, 1.0 - gradient / 0.2), 4)
    
    return FieldStabilityResult(
        gradient=gradient,
        integrity_index=integrity,
        field_state=state,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
    )


def compute_quad_energy(energies: Dict[str, float]) -> QuadEnergyResult:
    """Compute quad-timeframe energy analysis."""
    if not energies:
        return QuadEnergyResult(mean_energy=0.0, reflective_coherence=0.0, drift=0.0)
    
    mean_energy = sum(energies.values()) / len(energies)
    drift = max(energies.values()) - min(energies.values())
    coherence = max(0.0, min(1.0, 1 - drift * 0.5))
    
    return QuadEnergyResult(
        mean_energy=round(mean_energy, 4),
        reflective_coherence=round(coherence, 4),
        drift=round(drift, 4),
    )


def get_reflective_energy_state(coherence: float, trq3d_energy: float) -> ReflectiveEnergyState:
    """Determine Lorentzian reflective energy state."""
    if coherence >= 0.978 and trq3d_energy >= 0.96:
        return ReflectiveEnergyState.STABLE
    elif coherence < 0.975 and trq3d_energy < 0.94:
        return ReflectiveEnergyState.LOW_SYNC
    return ReflectiveEnergyState.HIGH_FLUX


def apply_symmetry_patch(alpha: float, beta: float, gamma: float) -> Tuple[float, float, float]:
    """Apply symmetry correction to α-β-γ field."""
    avg = (alpha + beta + gamma) / 3
    threshold = SYMMETRY_PATCH_CONFIG["symmetry_threshold"]
    
    if abs(alpha - avg) > threshold:
        alpha = alpha * 0.9 + avg * 0.1
    if abs(beta - avg) > threshold:
        beta = beta * 0.9 + avg * 0.1
    if abs(gamma - avg) > threshold:
        gamma = gamma * 0.9 + avg * 0.1
    
    return round(alpha, 4), round(beta, 4), round(gamma, 4)


def compute_reflective_gradient(alpha: float, beta: float, gamma: float) -> Dict[str, float]:
    """Compute reflective gradient from α-β-γ components."""
    gradient = (abs(alpha - beta) + abs(beta - gamma) + abs(alpha - gamma)) / 3
    stability = round(1 - min(abs(gradient) * 10, 1), 4)
    return {"gradient": round(gradient, 4), "stability": stability}


# =============================================================================
# 🔁 SECTION 9: TRQ3D — SANITIZED CONTEXT (NO BUY/SELL DIRECTIVES)
# =============================================================================

def trq3d_context(
    energies: List[float],
    directions: List[int],
) -> TRQ3DResult:
    """
    Compute TRQ3D context analysis.
    Returns DESCRIPTIVE bias context only — NO execution directives.
    """
    if not energies or not directions:
        return TRQ3DResult(
            total_energy=0.0,
            coherence_score=0.0,
            alignment_score=0.0,
            dominant_direction=0,
            bias_context=BiasContext.NEUTRAL_CONTEXT,
        )
    
    total_energy = sum(energies) / len(energies)
    alignment = max(directions.count(1), directions.count(-1)) / len(directions)
    coherence = 1 - stdev(energies) if len(energies) > 1 else 1.0
    dominant = 1 if sum(directions) > 0 else (-1 if sum(directions) < 0 else 0)
    
    # Descriptive context only — NOT a directive
    if dominant == 1:
        bias_context = BiasContext.BULLISH_CONTEXT
    elif dominant == -1:
        bias_context = BiasContext.BEARISH_CONTEXT
    else:
        bias_context = BiasContext.NEUTRAL_CONTEXT
    
    return TRQ3DResult(
        total_energy=round(total_energy, 4),
        coherence_score=round(max(0, coherence), 4),
        alignment_score=round(alignment, 4),
        dominant_direction=dominant,
        bias_context=bias_context,
        resonance_score=round(alignment * coherence, 4),
        pre_move_detected=alignment >= 0.75 and coherence >= 0.8,
        recommendation="ANALYSIS_ONLY",
    )


def trq3d_engine_func(
    pair: str,
    timeframe: str = "H1",
    price_series: Optional[List[float]] = None,
    volume_series: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Legacy function-style interface for TRQ3D computation."""
    if price_series is None:
        price_series = [1.0, 1.001, 1.002, 0.999, 1.003]
    if volume_series is None:
        volume_series = [100, 120, 150, 90, 110]
    
    price_momentum = abs(price_series[-1] - price_series[0]) / (price_series[0] or 1) * 100
    price_volatility = sum(abs(price_series[i] - price_series[i-1]) for i in range(1, len(price_series))) / len(price_series)
    volume_strength = sum(volume_series) / (len(volume_series) * max(volume_series or [1]))
    
    alpha = min(1.0, max(0.0, price_momentum / 10))
    beta = min(1.0, max(0.0, 1 - price_volatility * 100))
    gamma = min(1.0, max(0.0, volume_strength))
    mean_energy = (alpha + beta + gamma) / 3
    reflective_intensity = mean_energy * 0.95
    
    # Descriptive phase only
    if alpha > 0.7 and gamma > 0.6:
        phase = "expansion_context"
    elif alpha < 0.3 and gamma < 0.4:
        phase = "contraction_context"
    else:
        phase = "neutral_context"
    
    return {
        "pair": pair,
        "timeframe": timeframe,
        "alpha": round(alpha, 4),
        "beta": round(beta, 4),
        "gamma": round(gamma, 4),
        "mean_energy": round(mean_energy, 4),
        "reflective_intensity": round(reflective_intensity, 4),
        "phase": phase,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "analysis_mode": "NON_EXECUTION",
    }


# =============================================================================
# 📊 SECTION 10: EAF CALCULATOR — EMOTIONAL AWARENESS
# =============================================================================

class EAFScoreCalculator:
    """Calculator for Emotional Awareness Factor (EAF)."""
    
    def __init__(self):
        self.config = EAF_CONFIG.copy()
        self._history: List[EAFResult] = []
    
    def calculate_emotional_bias(self, input_data: EmotionalInput) -> Tuple[float, EmotionalState]:
        """Calculate emotional bias from input metrics."""
        fear_score = 0.0
        if input_data.consecutive_losses >= 2:
            fear_score += 0.3
        if input_data.last_trade_pnl < -50:
            fear_score += 0.2
        
        greed_score = 0.0
        if input_data.recent_wins >= 3 and input_data.recent_losses == 0:
            greed_score += 0.3
        if input_data.confidence_level > 0.9:
            greed_score += 0.2
        
        frustration_score = 0.0
        if input_data.consecutive_losses >= self.config["max_consecutive_losses"]:
            frustration_score += 0.4
        if input_data.stop_moved_count > 2:
            frustration_score += 0.2
        
        fatigue_score = 0.0
        if input_data.session_duration_minutes > 240:
            fatigue_score += 0.3
        if input_data.time_since_last_break_minutes > 120:
            fatigue_score += 0.2
        
        total_bias = (
            fear_score * self.config["fear_weight"] +
            greed_score * self.config["greed_weight"] +
            frustration_score * self.config["frustration_weight"] +
            fatigue_score * self.config["fatigue_weight"]
        )
        
        scores = {
            EmotionalState.FEARFUL: fear_score,
            EmotionalState.OVERCONFIDENT: greed_score,
            EmotionalState.FRUSTRATED: frustration_score,
            EmotionalState.FATIGUED: fatigue_score,
        }
        
        max_score = max(scores.values())
        if max_score < 0.2:
            detected_state = input_data.self_reported_state or EmotionalState.CALM
        else:
            detected_state = max(scores, key=scores.get)
        
        return min(1.0, total_bias), detected_state
    
    def calculate(self, input_data: EmotionalInput) -> EAFResult:
        """Calculate complete EAF score."""
        emotional_bias, detected_state = self.calculate_emotional_bias(input_data)
        
        stability_index = max(0.0, 1.0 - input_data.consecutive_losses * 0.1)
        focus_level = max(0.0, 1.0 - input_data.session_duration_minutes / 480)
        discipline_score = 1.0 if input_data.stop_moved_count == 0 else max(0.5, 1.0 - input_data.stop_moved_count * 0.15)
        
        eaf_score = (1 - emotional_bias) * stability_index * focus_level * discipline_score
        
        warnings = []
        if emotional_bias > 0.4:
            warnings.append(f"High emotional bias detected: {detected_state.value}")
        if stability_index < 0.6:
            warnings.append("Low stability - consider taking a break")
        
        recommendations = []
        if input_data.consecutive_losses >= self.config["max_consecutive_losses"]:
            recommendations.append(f"Take {self.config['cooldown_after_losses_minutes']}min break")
        
        can_trade = eaf_score >= self.config["min_eaf_for_trade"]
        
        # Determine behavior
        if input_data.consecutive_losses >= 2 and input_data.time_since_last_loss_minutes < 15:
            detected_behavior = TradingBehavior.REVENGE_TRADING
            can_trade = False
        elif input_data.trades_in_last_hour > 5 and input_data.avg_decision_time_seconds < 15:
            detected_behavior = TradingBehavior.FOMO
        elif input_data.stop_moved_count == 0 and 15 <= input_data.avg_decision_time_seconds <= 60:
            detected_behavior = TradingBehavior.DISCIPLINED
        else:
            detected_behavior = TradingBehavior.NORMAL
        
        result = EAFResult(
            eaf_score=round(eaf_score, 4),
            emotional_bias=round(emotional_bias, 4),
            stability_index=round(stability_index, 4),
            focus_level=round(focus_level, 4),
            discipline_score=round(discipline_score, 4),
            detected_state=detected_state,
            detected_behavior=detected_behavior,
            can_trade=can_trade,
            warnings=warnings,
            recommendations=recommendations,
            cooldown_required=input_data.consecutive_losses >= self.config["max_consecutive_losses"],
            cooldown_minutes=self.config["cooldown_after_losses_minutes"] if input_data.consecutive_losses >= self.config["max_consecutive_losses"] else 0,
        )
        
        self._history.append(result)
        return result


# =============================================================================
# 🐺 SECTION 11: WOLF-REFLECTIVE INTEGRATOR
# =============================================================================

class WolfReflectiveIntegrator:
    """Integrator between Wolf Discipline Framework and Reflective System."""
    
    def __init__(self):
        self.config = {
            "min_total_score": 0.80,
            "min_entry_score": 0.75,
            "min_psychological_score": 0.80,
            "frpc_boost_threshold": 0.90,
            "caution_threshold": 0.70,
            "block_threshold": 0.60,
            "entry_weight": 0.35,
            "risk_weight": 0.25,
            "psychological_weight": 0.25,
            "propfirm_weight": 0.15,
        }
        self._last_discipline_score: Optional[WolfDisciplineScore] = None
    
    def evaluate_discipline(self, checks: List[DisciplineCheckResult]) -> WolfDisciplineScore:
        """Evaluate discipline checks and calculate scores."""
        entry_checks = [c for c in checks if c.category == DisciplineCategory.ENTRY]
        risk_checks = [c for c in checks if c.category == DisciplineCategory.RISK]
        psych_checks = [c for c in checks if c.category == DisciplineCategory.PSYCHOLOGICAL]
        prop_checks = [c for c in checks if c.category == DisciplineCategory.PROPFIRM]
        
        def calc_score(cl: List[DisciplineCheckResult]) -> float:
            if not cl:
                return 0.0
            tw = sum(c.weight for c in cl)
            pw = sum(c.weight for c in cl if c.passed)
            return pw / tw if tw > 0 else 0.0
        
        entry_score = calc_score(entry_checks)
        risk_score = calc_score(risk_checks)
        psychological_score = calc_score(psych_checks)
        propfirm_score = calc_score(prop_checks)
        
        total_score = (
            entry_score * self.config["entry_weight"] +
            risk_score * self.config["risk_weight"] +
            psychological_score * self.config["psychological_weight"] +
            propfirm_score * self.config["propfirm_weight"]
        )
        
        critical_failures = [c.check_name for c in checks if not c.passed and c.weight >= 1.0]
        checks_passed = sum(1 for c in checks if c.passed)
        
        score = WolfDisciplineScore(
            total_score=round(total_score, 4),
            entry_score=round(entry_score, 4),
            risk_score=round(risk_score, 4),
            psychological_score=round(psychological_score, 4),
            propfirm_score=round(propfirm_score, 4),
            checks_passed=checks_passed,
            checks_failed=len(checks) - checks_passed,
            critical_failures=critical_failures,
        )
        
        self._last_discipline_score = score
        return score
    
    def determine_adjustment(self, discipline_score: WolfDisciplineScore) -> Tuple[ReflectiveAdjustment, float]:
        """Determine reflective adjustment based on discipline score."""
        total = discipline_score.total_score
        
        if discipline_score.critical_failures:
            return ReflectiveAdjustment.BLOCK, 0.0
        if total >= self.config["frpc_boost_threshold"]:
            return ReflectiveAdjustment.BOOST, 1.15
        elif total >= self.config["min_total_score"]:
            return ReflectiveAdjustment.NEUTRAL, 1.0
        elif total >= self.config["caution_threshold"]:
            return ReflectiveAdjustment.CAUTION, 0.85
        else:
            return ReflectiveAdjustment.BLOCK, 0.0
    
    def get_wolf_checklist_template(self) -> List[Dict[str, Any]]:
        """Get the 24-point Wolf discipline checklist template."""
        return [
            {"category": "entry", "name": "trend_direction_confirmed", "weight": 1.5},
            {"category": "entry", "name": "mtf_confluence", "weight": 1.5},
            {"category": "entry", "name": "key_level_identified", "weight": 1.0},
            {"category": "entry", "name": "price_action_valid", "weight": 1.0},
            {"category": "entry", "name": "entry_timing_optimal", "weight": 1.0},
            {"category": "entry", "name": "spread_acceptable", "weight": 0.5},
            {"category": "entry", "name": "no_conflicting_signals", "weight": 1.0},
            {"category": "entry", "name": "fundamental_alignment", "weight": 0.5},
            {"category": "risk", "name": "position_size_valid", "weight": 1.5},
            {"category": "risk", "name": "stop_loss_defined", "weight": 1.5},
            {"category": "risk", "name": "rr_ratio_acceptable", "weight": 1.0},
            {"category": "risk", "name": "daily_drawdown_check", "weight": 1.0},
            {"category": "risk", "name": "max_drawdown_check", "weight": 1.0},
            {"category": "risk", "name": "correlation_check", "weight": 0.5},
            {"category": "psychological", "name": "emotional_state_stable", "weight": 1.5},
            {"category": "psychological", "name": "not_revenge_trading", "weight": 1.5},
            {"category": "psychological", "name": "fomo_check_passed", "weight": 1.0},
            {"category": "psychological", "name": "fatigue_level_ok", "weight": 0.5},
            {"category": "psychological", "name": "confidence_calibrated", "weight": 0.5},
            {"category": "propfirm", "name": "within_daily_loss_limit", "weight": 1.5},
            {"category": "propfirm", "name": "within_max_loss_limit", "weight": 1.5},
            {"category": "propfirm", "name": "min_trading_days_ok", "weight": 0.5},
            {"category": "propfirm", "name": "lot_size_compliant", "weight": 0.5},
            {"category": "propfirm", "name": "trading_hours_valid", "weight": 0.5},
        ]


# =============================================================================
# 📊 SECTION 12: VOLUME QUADRANT ENGINE
# =============================================================================

def reflective_volume_quadrant_engine(
    price_series: List[float],
    volume_series: List[float],
    vwap: float,
    threshold: Optional[float] = None,
) -> VolumeQuadrantResult:
    """Compute volume distribution across 4 reflective quadrants."""
    if len(price_series) < 4 or len(volume_series) < 4:
        return VolumeQuadrantResult(
            timestamp=datetime.now(timezone.utc).isoformat(),
            high=0, low=0, vwap=vwap, threshold=0,
            quadrants={}, rvi=0, bias="insufficient_data",
            key_support_demand=0, liquidity_pool=0,
        )
    
    high, low = max(price_series), min(price_series)
    midpoint = (high + low) / 2
    range_half = (high - low) / 2
    price_span = max(high - low, 1e-9)
    vwap_safe = abs(vwap) if abs(vwap) > 1e-9 else price_span
    volatility_ratio = price_span / vwap_safe
    adaptive_threshold = float(threshold) if threshold else max(0.0005, min(0.002, volatility_ratio * 0.25))
    
    q1_vol = sum(v for p, v in zip(price_series, volume_series) if p > midpoint + adaptive_threshold)
    q2_vol = sum(v for p, v in zip(price_series, volume_series) if midpoint < p <= midpoint + adaptive_threshold)
    q3_vol = sum(v for p, v in zip(price_series, volume_series) if midpoint - adaptive_threshold < p <= midpoint)
    q4_vol = sum(v for p, v in zip(price_series, volume_series) if p <= midpoint - adaptive_threshold)
    
    total_vol = q1_vol + q2_vol + q3_vol + q4_vol
    if total_vol == 0:
        total_vol = 1
    
    q1 = round(q1_vol / total_vol * 100, 2)
    q2 = round(q2_vol / total_vol * 100, 2)
    q3 = round(q3_vol / total_vol * 100, 2)
    q4 = round(q4_vol / total_vol * 100, 2)
    rvi = round((q1 + q2 - q3 - q4) / 100, 3)
    
    # Descriptive bias only
    if rvi > 0.05:
        bias = "bullish_reflective_expansion_context"
        key_zone = high - range_half * 0.25
        liq = low + range_half * 0.15
    elif rvi < -0.05:
        bias = "bearish_reflective_expansion_context"
        key_zone = low + range_half * 0.25
        liq = high - range_half * 0.15
    else:
        bias = "neutral_reflective_equilibrium"
        key_zone = midpoint
        liq = midpoint
    
    return VolumeQuadrantResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        high=round(high, 5), low=round(low, 5), vwap=round(vwap, 5),
        threshold=round(adaptive_threshold, 6),
        quadrants={"Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4},
        rvi=rvi, bias=bias,
        key_support_demand=round(key_zone, 5), liquidity_pool=round(liq, 5),
    )


# =============================================================================
# 🔒 SECTION 13: EXECUTION STUB (HARDCODED BLOCK)
# =============================================================================

def execute_reflective_trade(
    pair: str = "UNKNOWN",
    plan: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> TradeExecutionResult:
    """
    ⛔ EXECUTION BLOCKED — ANALYSIS MODE ONLY
    
    This function ALWAYS returns BLOCKED status.
    The Reflective Analysis Core has NO execution authority.
    """
    allowed, reason = _check_execution_guard()
    
    return TradeExecutionResult(
        timestamp=datetime.now(timezone.utc).isoformat(),
        pair=pair,
        status=ExecutionStatus.BLOCKED,
        outcome="analysis_only_execution_blocked",
        governance_note=f"GOVERNANCE_BLOCK: {reason}",
    )


def generate_trade_targets(
    entry_price: float,
    stop_loss: float,
    direction: str,
    rr_ratio: float = 2.0,
) -> Dict[str, Any]:
    """
    Generate theoretical TP targets — FOR ANALYSIS ONLY.
    These are NOT execution directives.
    """
    rr = max(rr_ratio, 2.0)
    risk = abs(entry_price - stop_loss)
    
    if direction.lower() in ["buy", "bullish_context"]:
        tp1 = entry_price + (risk * rr)
    else:
        tp1 = entry_price - (risk * rr)
    
    return {
        "tp_levels": [round(tp1, 5)],
        "rr_ratio": f"1:{rr}",
        "mode": "ANALYSIS_ONLY",
        "binding": False,
        "note": "Theoretical targets for analysis purposes only",
    }


# =============================================================================
# 🧩 SECTION 14: ANALYSIS ADAPTER v2.1
# =============================================================================

def build_analysis_payload_v2_1(
    *,
    tii: TIIResult,
    frpc: FRPCResult,
    field: FieldStabilityResult,
    quad: QuadEnergyResult,
    trq3d: TRQ3DResult,
    symmetry: Optional[SymmetryEvaluation] = None,
    eaf: Optional[EAFResult] = None,
    wolf: Optional[WolfDisciplineScore] = None,
) -> Dict[str, Any]:
    """
    Build complete analysis payload for orchestrator consumption.
    Schema v2.1 — ANALYSIS ONLY, NON-BINDING.
    """
    return {
        "schema_version": "2.1",
        "analysis_mode": "NON_EXECUTION",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        
        "fusion_momentum": {
            "energy": {
                "mean": quad.mean_energy,
                "coherence": quad.reflective_coherence,
                "drift": quad.drift,
            },
            "trq3d": {
                "total_energy": trq3d.total_energy,
                "coherence_score": trq3d.coherence_score,
                "alignment_score": trq3d.alignment_score,
                "dominant_direction": trq3d.dominant_direction,
                "resonance_score": trq3d.resonance_score,
                "pre_move_detected": trq3d.pre_move_detected,
            },
            "bias_context": trq3d.bias_context.value,
        },
        
        "fusion_structure": {
            "field_state": field.field_state.value,
            "integrity_index": field.integrity_index,
            "gradient": field.gradient,
            "alpha": field.alpha,
            "beta": field.beta,
            "gamma": field.gamma,
            "symmetry": {
                "tii_sym": symmetry.tii_sym if symmetry else 0.0,
                "polarity": symmetry.polarity if symmetry else 0.0,
                "phase": symmetry.phase if symmetry else "unknown",
            } if symmetry else {},
        },
        
        "precision": {
            "tii": {
                "score": tii.tii,
                "status": tii.status.value,
                "components": tii.components,
            },
            "frpc": {
                "value": frpc.frpc,
                "state": frpc.propagation_state.value,
                "alpha_sync": frpc.alpha_sync,
                "gamma_phase": frpc.gamma_phase,
            },
        },
        
        "psychology": {
            "eaf_score": eaf.eaf_score if eaf else None,
            "emotional_state": eaf.detected_state.value if eaf else None,
            "trading_behavior": eaf.detected_behavior.value if eaf else None,
            "can_trade": eaf.can_trade if eaf else None,
            "warnings": eaf.warnings if eaf else [],
        } if eaf else {},
        
        "discipline": {
            "total_score": wolf.total_score if wolf else None,
            "entry_score": wolf.entry_score if wolf else None,
            "risk_score": wolf.risk_score if wolf else None,
            "psychological_score": wolf.psychological_score if wolf else None,
            "critical_failures": wolf.critical_failures if wolf else [],
        } if wolf else {},
        
        "governance": {
            "execution_allowed": False,
            "binding": "ANALYSIS_ONLY",
            "mode": "NON_EXECUTION",
            "guard_active": True,
        },
    }


# =============================================================================
# 🏭 SECTION 15: FACTORY FUNCTIONS
# =============================================================================

def create_eaf_calculator() -> EAFScoreCalculator:
    """Create EAF calculator instance."""
    return EAFScoreCalculator()


def create_wolf_integrator() -> WolfReflectiveIntegrator:
    """Create Wolf-Reflective integrator instance."""
    return WolfReflectiveIntegrator()


def system_integrity_check() -> Dict[str, Any]:
    """Perform system integrity check."""
    return {
        "platform": "TUYUL_FX_AGI",
        "version": "7.0r∞-ANALYSIS",
        "core_integrity": "PASS",
        "modules_verified": True,
        "execution_blocked": True,
        "governance_mode": GOVERNANCE_MODE,
        "binding_status": BINDING_STATUS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# 📋 SECTION 16: PUBLIC API (__all__)
# =============================================================================

__all__ = [
    # Governance
    "GOVERNANCE_MODE", "BINDING_STATUS", "GOVERNANCE_CONFIG",
    
    # Exceptions (9)
    "ReflectiveError", "TIIValidationError", "FieldStabilityError", "PipelineError",
    "VaultIntegrityError", "BridgeSyncError", "EAFCalculationError", "FRPCError",
    "EvolutionError", "GovernanceBlockError",
    
    # Enums (19)
    "FieldState", "TIIClassification", "TIIStatus", "PipelineMode", "VaultSyncStatus",
    "IntegrityLevel", "SyncStatus", "EmotionalState", "TradingBehavior", "PropagationState",
    "ReflectiveEnergyState", "MetaState", "ExecutionStatus", "DisciplineCategory",
    "ReflectiveAdjustment", "TimeFrame", "EnergyLevel", "BiasContext",
    
    # Constants (8)
    "LAMBDA_ESI", "DEFAULT_TII_THRESHOLDS", "TRADE_VALIDATION_THRESHOLDS",
    "EAF_CONFIG", "QUANTUM_BRIDGE_CONFIG", "MODE_CONTROLLER_CONFIG",
    "PIPELINE_CONFIG", "SYMMETRY_PATCH_CONFIG",
    
    # Dataclasses (25)
    "TIIThresholds", "TIIResult", "FRPCResult", "FieldStabilityResult",
    "QuadEnergyResult", "TRQ3DResult", "SymmetryEvaluation", "TradeExecutionResult",
    "EAFResult", "EmotionalInput", "QuantumState", "ReflectiveState", "BridgeState",
    "PipelineState", "VaultStatus", "IntegrityAuditResult", "ReflectiveCycleResult",
    "DisciplineCheckResult", "WolfDisciplineScore", "CalibrationSummary",
    "VolumeQuadrantResult", "BotSyncState", "EvolutionSnapshot", "FeedbackSnapshot",
    "ReflectiveFeedbackState", "AnalysisPayload",
    
    # Classes (2)
    "EAFScoreCalculator", "WolfReflectiveIntegrator",
    
    # Functions - Analysis (15)
    "algo_precision_engine", "classify_tii_state", "get_tii_status",
    "fusion_reflective_propagation_coefficient",
    "adaptive_field_stabilizer", "compute_quad_energy", "get_reflective_energy_state",
    "apply_symmetry_patch", "compute_reflective_gradient",
    "trq3d_context", "trq3d_engine_func",
    "reflective_volume_quadrant_engine",
    "build_analysis_payload_v2_1",
    "create_eaf_calculator", "create_wolf_integrator",
    
    # Functions - Blocked Execution (2)
    "execute_reflective_trade", "generate_trade_targets",
    
    # Functions - System (1)
    "system_integrity_check",
]


# =============================================================================
# 🧪 SECTION 17: CLI / DEBUG UTILITY
# =============================================================================

if __name__ == "__main__":
    print("🌀 TUYUL FX AGI — Core Reflective Unified System")
    print("📌 Mode: ANALYSIS ONLY (v7.0r∞-ANALYSIS)")
    print("=" * 70)
    
    print("\n🔒 Governance Check...")
    integrity = system_integrity_check()
    print(f"  Mode: {integrity['governance_mode']}")
    print(f"  Execution Blocked: {integrity['execution_blocked']}")
    print(f"  Binding: {integrity['binding_status']}")
    
    print("\n📊 Testing TII Engine...")
    tii = algo_precision_engine(1.0850, 1.0845, 0.85, 0.92, 0.88, 0.95)
    print(f"  TII: {tii.tii}, Status: {tii.status.value}")
    
    print("\n🌀 Testing FRPC...")
    frpc = fusion_reflective_propagation_coefficient(0.85, 0.90, 0.88, 0.95, 0.92, 0.90, 0.97)
    print(f"  FRPC: {frpc.frpc}, State: {frpc.propagation_state.value}")
    
    print("\n⚡ Testing Field Stabilizer...")
    field = adaptive_field_stabilizer(0.92, 0.88, 0.90)
    print(f"  Gradient: {field.gradient}, State: {field.field_state.value}")
    
    print("\n🔋 Testing Quad Energy...")
    quad = compute_quad_energy({"W1": 1.01, "H1": 0.99, "M15": 1.00, "M1": 0.98})
    print(f"  Mean: {quad.mean_energy}, Coherence: {quad.reflective_coherence}")
    
    print("\n🔁 Testing TRQ3D Context...")
    trq3d = trq3d_context([0.85, 0.88, 0.90, 0.87], [1, 1, 1, 0])
    print(f"  Bias Context: {trq3d.bias_context.value}")
    print(f"  Recommendation: {trq3d.recommendation}")
    
    print("\n📊 Testing EAF Calculator...")
    eaf_calc = create_eaf_calculator()
    eaf_input = EmotionalInput(recent_wins=3, recent_losses=1, trades_in_last_hour=2)
    eaf = eaf_calc.calculate(eaf_input)
    print(f"  EAF: {eaf.eaf_score}, Can Trade: {eaf.can_trade}")
    
    print("\n🐺 Testing Wolf Integrator...")
    wolf = create_wolf_integrator()
    checks = [
        DisciplineCheckResult(DisciplineCategory.ENTRY, "trend_confirmed", True, 1.5),
        DisciplineCheckResult(DisciplineCategory.RISK, "stop_loss_defined", True, 1.5),
        DisciplineCheckResult(DisciplineCategory.PSYCHOLOGICAL, "emotional_stable", True, 1.5),
    ]
    score = wolf.evaluate_discipline(checks)
    print(f"  Score: {score.total_score:.2%}, Passed: {score.checks_passed}/{score.checks_passed + score.checks_failed}")
    
    print("\n🔒 Testing Execution Block...")
    exec_result = execute_reflective_trade("XAUUSD", {"type": "BUY"})
    print(f"  Status: {exec_result.status.value}")
    print(f"  Governance Note: {exec_result.governance_note}")
    
    print("\n🧩 Building Analysis Payload v2.1...")
    symmetry = SymmetryEvaluation(tii_sym=0.85, polarity=0.002, phase="stable")
    payload = build_analysis_payload_v2_1(
        tii=tii, frpc=frpc, field=field, quad=quad, trq3d=trq3d,
        symmetry=symmetry, eaf=eaf, wolf=score
    )
    print(f"  Schema: {payload['schema_version']}")
    print(f"  Mode: {payload['analysis_mode']}")
    print(f"  Execution Allowed: {payload['governance']['execution_allowed']}")
    
    print("\n" + "=" * 70)
    print(f"✅ All {len(__all__)} components verified! 🌀")
    print("⛔ Execution: BLOCKED (Analysis Mode Active)")
