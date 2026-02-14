"""
Core Unified Modules — v7.4.1r∞ Constitutional Pipeline (PATCHED)
=================================================================

CHANGELOG v7.4.1:
  - FIX: CalibrationSummary name collision resolved (cognitive→CognitiveCalibrationSummary)
  - FIX: Fusion module exports expanded (was missing 30+ key classes)
  - FIX: MonteCarloResult collision handled via namespace alias
  - FIX: _clamp signature inconsistency documented (module-private, no export needed)

4-Core Architecture (PRODUCTION — Real Logic Implementations):

  core_cognitive_unified   → L0, L1, L5(partial), L7, L9, L11, L13
  core_fusion_unified      → L2, L4, L6, L7, L9
  core_quantum_unified     → L3, L8(partial), L9, L12, L13
  core_reflective_unified  → L1-L2, L3-L6, L8, L10-L13
  core_reflective_unified_analysis → ANALYSIS-ONLY layer (non-binding)

Status: PRODUCTION-READY — All stubs replaced + critical bugs patched.
Version: v7.4.1r∞
"""

__version__ = "7.4.1"
__codename__ = "Wolf 15-Layer Constitutional Pipeline (Patched)"

# ─── Core Cognitive (L0, L1, L5, L7, L9, L11, L13) ──────────────────────────

from .core_cognitive_unified import (
    # Exceptions
    CognitiveError,
    RiskCalculationError,
    ValidationError,
    InvalidInputError,
    # Enums
    CognitiveBias,
    MarketRegimeType,
    MarketRegime,
    TrendStrength,
    ReflexState,
    ConfidenceLevel,
    SmartMoneySignal,
    InstitutionalBias,
    Timeframe,
    # Dataclasses
    CognitiveState,
    EmotionFeedbackCycle,
    ReflexEmotionResult,
    RegimeAnalysis,
    SmartMoneyAnalysis,
    TWMSInput,
    TWMSResult,
    RiskAssessment,
    AdaptiveRiskResult,
    # CalibrationSummary collision fix: use explicit name
    CognitiveCalibrationSummary,
    CalibrationSummary as CognitiveCalibrationSummaryAlias,  # backward compat
    # Classes
    EmotionFeedbackEngine,
    ReflexEmotionCore,
    RegimeClassifier,
    IntegrityEngine,
    SmartMoneyDetector,
    TWMSCalculator,
    AdaptiveRiskCalculator,
    RiskFeedbackCalibrator,
    VaultRiskSync,
    # Functions
    montecarlo_validate,
    compute_reflex_emotion,
    reflex_check,
    calculate_risk,
    calibrate_risk,
    calculate_confluence_score,
    validate_cognitive_thresholds,
    calculate_risk_adjusted_score,
    # Constants
    COHERENCE_THRESHOLD,
    INTEGRITY_MINIMUM,
    TWMS_WEIGHT_D1,
    TWMS_WEIGHT_H4,
    TWMS_WEIGHT_H1,
    REFLEX_GATE_PASS,
    META_LEARNING_RATE,
    META_RESILIENCE_INDEX,
    META_RESONANCE_LIMIT,
)

# ─── Core Fusion (L2, L4, L6, L7, L9) ───────────────────────────────────────
# EXPANDED: Previously only 4 enums were exported.
# Now includes all key classes, with collision-prone names aliased.

from .core_fusion_unified import (
    # Exceptions
    FusionError,
    FusionComputeError,
    FusionInputError,
    FusionConfigError,
    # Enums
    FusionBiasMode,
    FusionState,
    MomentumBand,
    DivergenceType,
    DivergenceStrength,
    FusionAction,
    MarketState,
    TransitionState,
    LiquidityType,
    LiquidityStatus,
    ResonanceState,
    # Dataclasses
    FieldContext,
    FusionPrecisionResult,
    EquilibriumResult,
    DivergenceSignal,
    MultiDivergenceResult,
    AdaptiveUpdate,
    ConfidenceLineage,
    FTTCConfig,
    FTTCResult,
    QMatrixConfig,
    LiquidityZone,
    LiquidityMapResult,
    CoherenceAudit,
    # MonteCarloResult collision: fusion version aliased
    MonteCarloResult as FusionMonteCarloResult,
    # Field Sync
    resolve_field_context,
    sync_field_state,
    # Classes — Previously missing!
    EMAFusionEngine,
    FusionPrecisionEngine,
    FusionIntegrator,
    MultiIndicatorDivergenceDetector,
    AdaptiveThresholdController,
    MonteCarloConfidence,
    MultiEMAFusion,
    QMatrixGenerator,
    ReflectiveMonteCarlo,
    LiquidityZoneMapper,
    VaultMacroLayer,
    VolumeProfileAnalyzer,
    UltraFusionOrchestrator,
    UltraFusionOrchestratorV6,
    MicroAdapter,
    QuantumReflectiveEngine,
    HybridReflectiveCore,
    # Functions
    evaluate_fusion_metrics,
    aggregate_multi_timeframe_metrics,
    calculate_fusion_precision,
    equilibrium_momentum_fusion_v6,
    equilibrium_momentum_fusion,
    integrate_fusion_layers,
    multi_timeframe_alignment_analyzer,
    phase_resonance_engine_v1_5,
    audit_reflective_coherence,
    create_fttc_engine,
    validate_price_data,
    normalize_timeframe,
    calculate_rr_ratio,
    calculate_wlwci,
    get_wlwci_config,
    rsi_alignment_engine,
    smart_money_counter_v3_5_reflective,
    # Dataclasses (new components)
    VolumeZoneType,
    VolumeProfileResult,
    VolumeZone,
    CounterZoneContext,
    VolatilityRegime,
    MicroBounds,
    NormalizedMicro,
    # Config
    WLWCI_CONFIG,
)

# ─── Core Quantum (L3, L8, L9, L12, L13) ─────────────────────────────────────

from .core_quantum_unified import (
    # Enums
    DecisionType,
    DecisionConfidence,
    TreeAction,
    ExecutionType,
    BattleStrategy,
    # Dataclasses
    FieldSummary,
    DriftAnalysis,
    QuantumDecision,
    TreeDecision,
    ExecutionPlan,
    ScenarioSelection,
    MonteCarloResult,  # Quantum version takes precedence (used in L12)
    ConfidenceResult,
    # Classes
    TRQ3DEngine,
    QuantumFieldSync,
    NeuralDecisionTree,
    QuantumDecisionEngine,
    ProbabilityMatrixCalculator,
    ConfidenceMultiplier,
    QuantumExecutionOptimizer,
    QuantumScenarioMatrix,
    # Functions
    analyze_drift,
    calculate_tii,
    monte_carlo_fttc_simulation,
    get_wolf_message,
)

# ─── Core Reflective (L1-L2, L3-L6, L8, L10-L13) ────────────────────────────

from .core_reflective_unified import (
    # Enums
    FieldState,
    TIIClassification,
    TIIStatus,
    PipelineMode,
    VaultSyncStatus,
    IntegrityLevel,
    PropagationState,
    ReflectiveEnergyState,
    MetaState,
    DisciplineCategory,
    # Dataclasses
    TIIResult,
    FRPCResult,
    FieldStabilityResult,
    # Reflective CalibrationSummary (different from cognitive!)
    CalibrationSummary as ReflectiveCalibrationSummary,
)

# ─── Core Reflective Analysis (ANALYSIS-ONLY, Non-Binding) ───────────────────

from .core_reflective_unified_analysis import (
    build_analysis_payload_v2_1,
    system_integrity_check,
    GOVERNANCE_MODE,
    BINDING_STATUS,
)

# ─── Public API ───────────────────────────────────────────────────────────────

__all__ = [
    # Version
    "__version__",
    "__codename__",
    # ── Cognitive ──
    "CognitiveError",
    "RiskCalculationError",
    "ValidationError",
    "InvalidInputError",
    "CognitiveBias",
    "MarketRegimeType",
    "MarketRegime",
    "TrendStrength",
    "ReflexState",
    "ConfidenceLevel",
    "SmartMoneySignal",
    "InstitutionalBias",
    "Timeframe",
    "CognitiveState",
    "EmotionFeedbackCycle",
    "ReflexEmotionResult",
    "RegimeAnalysis",
    "SmartMoneyAnalysis",
    "TWMSInput",
    "TWMSResult",
    "RiskAssessment",
    "AdaptiveRiskResult",
    "CognitiveCalibrationSummary",
    "EmotionFeedbackEngine",
    "ReflexEmotionCore",
    "RegimeClassifier",
    "IntegrityEngine",
    "SmartMoneyDetector",
    "TWMSCalculator",
    "AdaptiveRiskCalculator",
    "RiskFeedbackCalibrator",
    "VaultRiskSync",
    "montecarlo_validate",
    "compute_reflex_emotion",
    "reflex_check",
    "calculate_risk",
    "calibrate_risk",
    "calculate_confluence_score",
    "validate_cognitive_thresholds",
    "calculate_risk_adjusted_score",
    "COHERENCE_THRESHOLD",
    "INTEGRITY_MINIMUM",
    "REFLEX_GATE_PASS",
    # ── Fusion ──
    "FusionError",
    "FusionComputeError",
    "FusionInputError",
    "FusionConfigError",
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
    "FieldContext",
    "FusionPrecisionResult",
    "EquilibriumResult",
    "DivergenceSignal",
    "MultiDivergenceResult",
    "AdaptiveUpdate",
    "ConfidenceLineage",
    "FusionMonteCarloResult",
    "FTTCConfig",
    "FTTCResult",
    "QMatrixConfig",
    "LiquidityZone",
    "LiquidityMapResult",
    "CoherenceAudit",
    "resolve_field_context",
    "sync_field_state",
    "EMAFusionEngine",
    "FusionPrecisionEngine",
    "FusionIntegrator",
    "MultiIndicatorDivergenceDetector",
    "AdaptiveThresholdController",
    "MonteCarloConfidence",
    "MultiEMAFusion",
    "QMatrixGenerator",
    "ReflectiveMonteCarlo",
    "LiquidityZoneMapper",
    "VaultMacroLayer",
    "VolumeProfileAnalyzer",
    "UltraFusionOrchestrator",
    "UltraFusionOrchestratorV6",
    "MicroAdapter",
    "QuantumReflectiveEngine",
    "HybridReflectiveCore",
    "evaluate_fusion_metrics",
    "aggregate_multi_timeframe_metrics",
    "calculate_fusion_precision",
    "equilibrium_momentum_fusion",
    "integrate_fusion_layers",
    "multi_timeframe_alignment_analyzer",
    "audit_reflective_coherence",
    "create_fttc_engine",
    "validate_price_data",
    "calculate_wlwci",
    "rsi_alignment_engine",
    "smart_money_counter_v3_5_reflective",
    "VolumeZoneType",
    "VolumeProfileResult",
    "VolumeZone",
    "CounterZoneContext",
    "VolatilityRegime",
    "WLWCI_CONFIG",
    # ── Quantum ──
    "DecisionType",
    "DecisionConfidence",
    "TreeAction",
    "ExecutionType",
    "BattleStrategy",
    "FieldSummary",
    "DriftAnalysis",
    "QuantumDecision",
    "TreeDecision",
    "ExecutionPlan",
    "ScenarioSelection",
    "MonteCarloResult",
    "ConfidenceResult",
    "TRQ3DEngine",
    "QuantumFieldSync",
    "NeuralDecisionTree",
    "QuantumDecisionEngine",
    "ProbabilityMatrixCalculator",
    "ConfidenceMultiplier",
    "QuantumExecutionOptimizer",
    "QuantumScenarioMatrix",
    "analyze_drift",
    "calculate_tii",
    "monte_carlo_fttc_simulation",
    "get_wolf_message",
    # ── Reflective ──
    "FieldState",
    "TIIClassification",
    "TIIStatus",
    "PipelineMode",
    "VaultSyncStatus",
    "IntegrityLevel",
    "PropagationState",
    "ReflectiveEnergyState",
    "MetaState",
    "DisciplineCategory",
    "TIIResult",
    "FRPCResult",
    "FieldStabilityResult",
    "ReflectiveCalibrationSummary",
    # ── Analysis ──
    "build_analysis_payload_v2_1",
    "system_integrity_check",
    "GOVERNANCE_MODE",
    "BINDING_STATUS",
]
