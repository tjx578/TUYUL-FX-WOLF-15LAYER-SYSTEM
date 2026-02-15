"""
TUYUL FX - Engine Facade Layer v2.0

9 focused analysis engines that provide clean, testable API
over the monolithic core unified modules.

Architecture:
  Cognitive Domain (internal state awareness):
    - CognitiveCoherenceEngine  -> emotion/reflex/integrity
    - CognitiveContextEngine    -> regime/structure/liquidity
    - CognitiveRiskSimulation   -> stress testing/tail risk

  Fusion Domain (technical analysis fusion):
    - FusionMomentumEngine      -> momentum/phase/TRQ energy
    - FusionPrecisionEngine     -> precision weights/EMA alignment
    - FusionStructureEngine     -> divergence/liquidity/MTF

  Quantum Domain (probabilistic analysis):
    - QuantumFieldEngine        -> field energy/bias/stability
    - QuantumProbabilityEngine  -> layer probability/uncertainty
    - QuantumAdvisoryEngine     -> cross-engine synthesis

Usage:
    from engines import create_engine_suite
    suite = create_engine_suite()
    # ... use suite["coherence"].evaluate(state)
"""

from __future__ import annotations

__version__ = "2.0.0"
__codename__ = "Wolf Engine Facade"

# --- Cognitive ---
from .cognitive_coherence_engine import (
    CognitiveCoherence,  # pyright: ignore[reportAttributeAccessIssue]
    CognitiveCoherenceEngine,
    CoherenceGate,  # pyright: ignore[reportAttributeAccessIssue]
    CoherenceResult,  # pyright: ignore[reportAttributeAccessIssue]
    CoherenceState,
    IntegrityStatus,  # pyright: ignore[reportAttributeAccessIssue]
    ReflexState,  # pyright: ignore[reportAttributeAccessIssue]
)
from .cognitive_context_engine import (
    CognitiveContext,
    CognitiveContextEngine,
    ContextResult,  # pyright: ignore[reportAttributeAccessIssue]
    InstitutionalPresence,
    LiquidityContext,
    MarketRegime,
    MarketStructure,
)
from .cognitive_risk_simulation import CognitiveRiskSimulation, RiskSimulationResult

# --- Fusion ---
from .fusion_momentum_engine import (
    FusionMomentum,  # pyright: ignore[reportAttributeAccessIssue]
    FusionMomentumEngine,
    MomentumBand,  # pyright: ignore[reportAttributeAccessIssue]
    MomentumPhase,  # pyright: ignore[reportAttributeAccessIssue]
    MomentumResult,
)
from .fusion_precision_engine import (
    FusionPrecision,  # pyright: ignore[reportAttributeAccessIssue]
    FusionPrecisionEngine,
    PrecisionResult,  # pyright: ignore[reportAttributeAccessIssue]
)
from .fusion_structure_engine import (
    FusionStructure,  # pyright: ignore[reportAttributeAccessIssue]
    FusionStructureEngine,
    StructureResult,  # pyright: ignore[reportAttributeAccessIssue]
    StructureState,  # pyright: ignore[reportAttributeAccessIssue]
)

# --- Quantum ---
from .quantum_advisory_engine import (
    AdvisorySignal,  # pyright: ignore[reportAttributeAccessIssue]
    AdvisorySummary,  # pyright: ignore[reportAttributeAccessIssue]
    QuantumAdvisoryEngine,
    RiskPosture,  # pyright: ignore[reportAttributeAccessIssue]
)
from .quantum_field_engine import FieldResult, QuantumFieldEngine
from .quantum_probability_engine import (
    DEFAULT_LAYER_WEIGHTS,  # pyright: ignore[reportAttributeAccessIssue]
    ProbabilityResult,  # pyright: ignore[reportAttributeAccessIssue]
    QuantumProbabilityEngine,  # pyright: ignore[reportAttributeAccessIssue]
)


def create_engine_suite() -> dict[str, object]:
    """Factory: create all 9 engines with default configuration.

    Returns:
        Dict of engine_name -> engine_instance
    """
    return {
        "coherence": CognitiveCoherenceEngine(),
        "context": CognitiveContextEngine(),
        "risk_sim": CognitiveRiskSimulation(),
        "momentum": FusionMomentumEngine(),
        "precision": FusionPrecisionEngine(),
        "structure": FusionStructureEngine(),
        "field": QuantumFieldEngine(),
        "probability": QuantumProbabilityEngine(),
        "advisory": QuantumAdvisoryEngine(),
    }
__all__ = [
    "DEFAULT_LAYER_WEIGHTS",
    # Quantum types
    "AdvisorySignal",
    "AdvisorySummary",
    "BayesianProbabilityEngine", # type: ignore
    "BayesianResult", # type: ignore
    "CognitiveCoherence",
    # Cognitive engines
    "CognitiveCoherenceEngine",
    "CognitiveContext",
    "CognitiveContextEngine",
    "CognitiveRiskSimulation",
    # Cognitive types
    "CoherenceGate",
    "CoherenceResult",
    "CoherenceState",
    "ContextResult",
    # Correlation
    "CorrelationRiskEngine", # pyright: ignore[reportUnsupportedDunderAll]
    "CorrelationRiskResult", # pyright: ignore[reportUnsupportedDunderAll]
    "FieldResult",
    # Fusion types
    "FusionMomentum",
    # Fusion engines
    "FusionMomentumEngine",
    "FusionPrecision",
    "FusionPrecisionEngine",
    "FusionStructure",
    "FusionStructureEngine",
    "InstitutionalPresence",
    "IntegrityStatus",
    "LiquidityContext",
    "MarketRegime",
    "MarketStructure",
    "MomentumBand",
    "MomentumPhase",
    "MomentumResult",
    # Probability engines (Layer 7)
    "MonteCarloEngine", # pyright: ignore[reportUnsupportedDunderAll]
    "MonteCarloResult", # pyright: ignore[reportUnsupportedDunderAll]
    "PrecisionResult",
    "ProbabilityResult",
    # Quantum engines
    "QuantumAdvisoryEngine",
    "QuantumFieldEngine",
    "QuantumProbabilityEngine",
    "ReflexState",
    "RegimeClassification", # pyright: ignore[reportUnsupportedDunderAll]
    # Regime
    "RegimeClassifier", # pyright: ignore[reportUnsupportedDunderAll]
    "RiskPosture",
    "RiskSimulationResult",
    "StructureResult",
    "StructureState",
    "VolatilityClusterResult", # pyright: ignore[reportUnsupportedDunderAll]
    # Volatility Clustering
    "VolatilityClusteringModel", # pyright: ignore[reportUnsupportedDunderAll]
    "WalkForwardResult", # pyright: ignore[reportUnsupportedDunderAll]
    # Walk-Forward
    "WalkForwardValidator", # pyright: ignore[reportUnsupportedDunderAll]
    # Factory
    "create_engine_suite",
]
