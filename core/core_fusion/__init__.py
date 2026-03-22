"""
core.fusion -- TUYUL FX Modular Fusion Package v7.0r∞
=====================================================

Refactored dari core_fusion_unified.py (5,330 LOC, 175KB)
ke 20 sub-modules untuk maintainability dan testability.

100% backward-compatible: semua import yang sebelumnya bekerja
dari core_fusion_unified tetap bekerja dari core.fusion.

Usage:
    # Cara lama (tetap bekerja):
    from core.fusion import FusionIntegrator, calculate_wlwci

    # Cara baru (import spesifik):
    from core.fusion.integrator import FusionIntegrator
    from core.fusion.wlwci_calculator import calculate_wlwci
"""

# ── Types: Exceptions, Enums, Constants, Dataclasses ─────────────────────────
from ._types import (
    AdaptiveUpdate,
    CoherenceAudit,
    ConfidenceLineage,
    CounterZoneContext,
    DivergenceSignal,
    DivergenceStrength,
    DivergenceType,
    EquilibriumResult,
    FieldContext,
    FTTCConfig,
    FTTCResult,
    FusionAction,
    FusionBiasMode,
    FusionComputeError,
    FusionConfigError,
    FusionError,
    FusionInputError,
    FusionPrecisionResult,
    FusionState,
    LiquidityMapResult,
    LiquidityStatus,
    LiquidityType,
    LiquidityZone,
    MarketState,
    MicroBounds,
    MomentumBand,
    MonteCarloResult,
    MultiDivergenceResult,
    NormalizedMicro,
    QMatrixConfig,
    ResonanceState,
    TransitionState,
    VolatilityRegime,
    VolumeProfileResult,
    VolumeZone,
    VolumeZoneType,
)

# ── Utilities ─────────────────────────────────────────────────────────────────
from ._utils import (
    calculate_rr_ratio,
    exponential_moving_average,
    moving_average,
    normalize_timeframe,
    timestamp_now,
    validate_price_data,
    write_json_atomic,
    write_jsonl_atomic,
)

# ── Adaptive Threshold ────────────────────────────────────────────────────────
from .adaptive_threshold import AdaptiveThresholdController

# ── Smart Money Counter Zone ──────────────────────────────────────────────────
from .counter_zone import smart_money_counter_v3_5_reflective

# ── Divergence Detector ───────────────────────────────────────────────────────
from .divergence import MultiIndicatorDivergenceDetector

# ── EMA Engine ────────────────────────────────────────────────────────────────
from .ema_engine import EMAFusionEngine, MultiEMAFusion

# ── Equilibrium Momentum ──────────────────────────────────────────────────────
from .equilibrium import equilibrium_momentum_fusion, equilibrium_momentum_fusion_v6

# ── Field Sync ────────────────────────────────────────────────────────────────
from .field_sync import resolve_field_context, sync_field_state

# ── Hybrid Vault Quantum Engine ───────────────────────────────────────────────
from .hybrid_quantum import HybridReflectiveCore, QuantumReflectiveEngine

# ── Fusion Integrator (Layer 12) ──────────────────────────────────────────────
from .integrator import FusionIntegrator, integrate_fusion_layers

# ── Liquidity Zone Mapper ─────────────────────────────────────────────────────
from .liquidity_mapper import LiquidityZoneMapper

# ── Micro Adapter ─────────────────────────────────────────────────────────────
from .micro_adapter import MicroAdapter

# ── Monte Carlo Engines ───────────────────────────────────────────────────────
from .monte_carlo import MonteCarloConfidence, ReflectiveMonteCarlo, create_fttc_engine

# ── MTF Analyzer + Coherence Auditor ──────────────────────────────────────────
from .mtf_analyzer import audit_reflective_coherence, multi_timeframe_alignment_analyzer

# ── Ultra Fusion Orchestrator ─────────────────────────────────────────────────
from .orchestrator import UltraFusionOrchestrator, UltraFusionOrchestratorV6

# ── Phase Resonance ───────────────────────────────────────────────────────────
from .phase_resonance import phase_resonance_engine_v1_5

# ── Precision Engine + Metrics ────────────────────────────────────────────────
from .precision_engine import (
    FusionPrecisionEngine,
    aggregate_multi_timeframe_metrics,
    calculate_fusion_precision,
    evaluate_fusion_metrics,
)

# ── Q-Matrix Generator ───────────────────────────────────────────────────────
from .q_matrix import QMatrixGenerator

# ── RSI Alignment Engine ─────────────────────────────────────────────────────
from .rsi_alignment import rsi_alignment_engine

# ── Vault Macro Engine ────────────────────────────────────────────────────────
from .vault_macro import VaultMacroLayer

# ── Volume Profile Analyzer ───────────────────────────────────────────────────
from .volume_profile import VolumeProfileAnalyzer

# ── WLWCI Calculator ─────────────────────────────────────────────────────────
from .wlwci_calculator import WLWCI_CONFIG, calculate_wlwci, get_wlwci_config

__all__ = [
    # Exceptions
    "FusionError",
    "FusionComputeError",
    "FusionInputError",
    "FusionConfigError",
    # Enums
    "FusionBiasMode",
    "FusionState",
    "MomentumBand",
    "DivergenceType",
    "DivergenceStrength",
    "FusionAction",
    "MarketState",
    "TransitionState",
    "LiquidityType",
    "LiquidityStatus",
    "ResonanceState",
    "VolumeZoneType",
    "VolatilityRegime",
    # Dataclasses
    "FieldContext",
    "FusionPrecisionResult",
    "EquilibriumResult",
    "DivergenceSignal",
    "MultiDivergenceResult",
    "AdaptiveUpdate",
    "ConfidenceLineage",
    "MonteCarloResult",
    "FTTCConfig",
    "FTTCResult",
    "QMatrixConfig",
    "LiquidityZone",
    "LiquidityMapResult",
    "CoherenceAudit",
    "VolumeProfileResult",
    "VolumeZone",
    "CounterZoneContext",
    "NormalizedMicro",
    "MicroBounds",
    # Utilities
    "validate_price_data",
    "normalize_timeframe",
    "calculate_rr_ratio",
    "timestamp_now",
    "write_jsonl_atomic",
    "write_json_atomic",
    "moving_average",
    "exponential_moving_average",
    # Field Sync
    "resolve_field_context",
    "sync_field_state",
    # EMA
    "EMAFusionEngine",
    "MultiEMAFusion",
    # Precision + Metrics
    "FusionPrecisionEngine",
    "calculate_fusion_precision",
    "evaluate_fusion_metrics",
    "aggregate_multi_timeframe_metrics",
    # Equilibrium
    "equilibrium_momentum_fusion_v6",
    "equilibrium_momentum_fusion",
    # Divergence
    "MultiIndicatorDivergenceDetector",
    # Adaptive Threshold
    "AdaptiveThresholdController",
    # Integrator
    "FusionIntegrator",
    "integrate_fusion_layers",
    # Monte Carlo
    "MonteCarloConfidence",
    "ReflectiveMonteCarlo",
    "create_fttc_engine",
    # MTF
    "multi_timeframe_alignment_analyzer",
    "audit_reflective_coherence",
    # Phase Resonance
    "phase_resonance_engine_v1_5",
    # Q-Matrix
    "QMatrixGenerator",
    # Liquidity
    "LiquidityZoneMapper",
    # Vault Macro
    "VaultMacroLayer",
    # Volume Profile
    "VolumeProfileAnalyzer",
    # WLWCI
    "WLWCI_CONFIG",
    "get_wlwci_config",
    "calculate_wlwci",
    # RSI Alignment
    "rsi_alignment_engine",
    # Counter Zone
    "smart_money_counter_v3_5_reflective",
    # Orchestrator
    "UltraFusionOrchestrator",
    "UltraFusionOrchestratorV6",
    # Micro Adapter
    "MicroAdapter",
    # Hybrid Quantum
    "QuantumReflectiveEngine",
    "HybridReflectiveCore",
]
