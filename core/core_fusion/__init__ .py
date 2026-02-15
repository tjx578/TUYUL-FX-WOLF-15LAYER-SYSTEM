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
    FusionError, FusionComputeError, FusionInputError, FusionConfigError,
    FusionBiasMode, FusionState, MomentumBand, DivergenceType, DivergenceStrength,
    FusionAction, MarketState, TransitionState, LiquidityType, LiquidityStatus,
    ResonanceState, VolumeZoneType, VolatilityRegime,
    FieldContext, FusionPrecisionResult, EquilibriumResult, DivergenceSignal,
    MultiDivergenceResult, AdaptiveUpdate, ConfidenceLineage, MonteCarloResult,
    FTTCConfig, FTTCResult, QMatrixConfig, LiquidityZone, LiquidityMapResult,
    CoherenceAudit, VolumeProfileResult, VolumeZone, CounterZoneContext,
    NormalizedMicro, MicroBounds,
)

# ── Utilities ─────────────────────────────────────────────────────────────────
from ._utils import (
    validate_price_data, normalize_timeframe, calculate_rr_ratio,
    timestamp_now, write_jsonl_atomic, write_json_atomic,
    moving_average, exponential_moving_average,
)

# ── Field Sync ────────────────────────────────────────────────────────────────
from .field_sync import resolve_field_context, sync_field_state

# ── EMA Engine ────────────────────────────────────────────────────────────────
from .ema_engine import EMAFusionEngine, MultiEMAFusion

# ── Precision Engine + Metrics ────────────────────────────────────────────────
from .precision_engine import (
    FusionPrecisionEngine, calculate_fusion_precision,
    evaluate_fusion_metrics, aggregate_multi_timeframe_metrics,
)

# ── Equilibrium Momentum ──────────────────────────────────────────────────────
from .equilibrium import equilibrium_momentum_fusion_v6, equilibrium_momentum_fusion

# ── Divergence Detector ───────────────────────────────────────────────────────
from .divergence import MultiIndicatorDivergenceDetector

# ── Adaptive Threshold ────────────────────────────────────────────────────────
from .adaptive_threshold import AdaptiveThresholdController

# ── Fusion Integrator (Layer 12) ──────────────────────────────────────────────
from .integrator import FusionIntegrator, integrate_fusion_layers

# ── Monte Carlo Engines ───────────────────────────────────────────────────────
from .monte_carlo import MonteCarloConfidence, ReflectiveMonteCarlo, create_fttc_engine

# ── MTF Analyzer + Coherence Auditor ──────────────────────────────────────────
from .mtf_analyzer import multi_timeframe_alignment_analyzer, audit_reflective_coherence

# ── Phase Resonance ───────────────────────────────────────────────────────────
from .phase_resonance import phase_resonance_engine_v1_5

# ── Q-Matrix Generator ───────────────────────────────────────────────────────
from .q_matrix import QMatrixGenerator

# ── Liquidity Zone Mapper ─────────────────────────────────────────────────────
from .liquidity_mapper import LiquidityZoneMapper

# ── Vault Macro Engine ────────────────────────────────────────────────────────
from .vault_macro import VaultMacroLayer

# ── Volume Profile Analyzer ───────────────────────────────────────────────────
from .volume_profile import VolumeProfileAnalyzer

# ── WLWCI Calculator ─────────────────────────────────────────────────────────
from .wlwci_calculator import WLWCI_CONFIG, get_wlwci_config, calculate_wlwci

# ── RSI Alignment Engine ─────────────────────────────────────────────────────
from .rsi_alignment import rsi_alignment_engine

# ── Smart Money Counter Zone ──────────────────────────────────────────────────
from .counter_zone import smart_money_counter_v3_5_reflective

# ── Ultra Fusion Orchestrator ─────────────────────────────────────────────────
from .orchestrator import UltraFusionOrchestrator, UltraFusionOrchestratorV6

# ── Micro Adapter ─────────────────────────────────────────────────────────────
from .micro_adapter import MicroAdapter

# ── Hybrid Vault Quantum Engine ───────────────────────────────────────────────
from .hybrid_quantum import QuantumReflectiveEngine, HybridReflectiveCore


__all__ = [
    # Exceptions
    "FusionError", "FusionComputeError", "FusionInputError", "FusionConfigError",
    # Enums
    "FusionBiasMode", "FusionState", "MomentumBand", "DivergenceType", "DivergenceStrength",
    "FusionAction", "MarketState", "TransitionState", "LiquidityType", "LiquidityStatus",
    "ResonanceState", "VolumeZoneType", "VolatilityRegime",
    # Dataclasses
    "FieldContext", "FusionPrecisionResult", "EquilibriumResult", "DivergenceSignal",
    "MultiDivergenceResult", "AdaptiveUpdate", "ConfidenceLineage", "MonteCarloResult",
    "FTTCConfig", "FTTCResult", "QMatrixConfig", "LiquidityZone", "LiquidityMapResult",
    "CoherenceAudit", "VolumeProfileResult", "VolumeZone", "CounterZoneContext",
    "NormalizedMicro", "MicroBounds",
    # Utilities
    "validate_price_data", "normalize_timeframe", "calculate_rr_ratio",
    "timestamp_now", "write_jsonl_atomic", "write_json_atomic",
    "moving_average", "exponential_moving_average",
    # Field Sync
    "resolve_field_context", "sync_field_state",
    # EMA
    "EMAFusionEngine", "MultiEMAFusion",
    # Precision + Metrics
    "FusionPrecisionEngine", "calculate_fusion_precision",
    "evaluate_fusion_metrics", "aggregate_multi_timeframe_metrics",
    # Equilibrium
    "equilibrium_momentum_fusion_v6", "equilibrium_momentum_fusion",
    # Divergence
    "MultiIndicatorDivergenceDetector",
    # Adaptive Threshold
    "AdaptiveThresholdController",
    # Integrator
    "FusionIntegrator", "integrate_fusion_layers",
    # Monte Carlo
    "MonteCarloConfidence", "ReflectiveMonteCarlo", "create_fttc_engine",
    # MTF
    "multi_timeframe_alignment_analyzer", "audit_reflective_coherence",
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
    "WLWCI_CONFIG", "get_wlwci_config", "calculate_wlwci",
    # RSI Alignment
    "rsi_alignment_engine",
    # Counter Zone
    "smart_money_counter_v3_5_reflective",
    # Orchestrator
    "UltraFusionOrchestrator", "UltraFusionOrchestratorV6",
    # Micro Adapter
    "MicroAdapter",
    # Hybrid Quantum
    "QuantumReflectiveEngine", "HybridReflectiveCore",
]
