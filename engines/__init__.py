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
    CognitiveCoherenceEngine,
    CoherenceSnapshot,
    CoherenceState,
)
from .cognitive_context_engine import (
    CognitiveContext,
    CognitiveContextEngine,
    InstitutionalPresence,
    LiquidityContext,
    MarketRegime,
    MarketStructure,
)
from .cognitive_risk_simulation import CognitiveRiskSimulation, RiskSimulationResult

# --- Fusion ---
from .fusion_momentum_engine import (
    FusionMomentumEngine,
    MomentumResult,
)
from .fusion_precision_engine import (
    FusionPrecisionEngine,
    PrecisionResult,
)
from .fusion_structure_engine import (
    FusionStructureEngine,
    StructureResult,
)

# --- Quantum ---
from .quantum_advisory_engine import (
    AdvisoryResult,
    QuantumAdvisoryEngine,
)
from .quantum_field_engine import FieldResult, QuantumFieldEngine
from .quantum_probability_engine import (
    ProbabilityResult,
    QuantumProbabilityEngine,
)


def create_engine_suite() -> dict[str, object]:
    """Factory: create all 9 engines with default configuration.

    Returns:
        Dict of engine_name -> engine_instance
    """
    return {
        "coherence": CognitiveCoherenceEngine(),
        "context": CognitiveContextEngine(),
        "risk_sim": CognitiveRiskSimulation(),  # also aliased as "risk"
        "risk": CognitiveRiskSimulation(),  # alias for backward compat
        "momentum": FusionMomentumEngine(),
        "precision": FusionPrecisionEngine(),
        "structure": FusionStructureEngine(),
        "field": QuantumFieldEngine(),
        "probability": QuantumProbabilityEngine(),
        "advisory": QuantumAdvisoryEngine(),
    }
__all__ = [
    # Quantum types
    "AdvisoryResult",
    # Cognitive engines
    "CognitiveCoherenceEngine",
    "CognitiveContext",
    "CognitiveContextEngine",
    "CognitiveRiskSimulation",
    # Cognitive types
    "CoherenceSnapshot",
    "CoherenceState",
    "FieldResult",
    # Fusion engines
    "FusionMomentumEngine",
    "FusionPrecisionEngine",
    "FusionStructureEngine",
    "InstitutionalPresence",
    "LiquidityContext",
    "MarketRegime",
    "MarketStructure",
    # Fusion types
    "MomentumResult",
    "PrecisionResult",
    "ProbabilityResult",
    # Quantum engines
    "QuantumAdvisoryEngine",
    "QuantumFieldEngine",
    "QuantumProbabilityEngine",
    "RiskSimulationResult",
    "StructureResult",
    # Factory
    "create_engine_suite",
]

# ------------------------------------------------------------------
# Backward Compatibility: CognitiveCoherence Export
# ------------------------------------------------------------------
def __getattr__(name):
    if name == "CognitiveCoherence":
        try:
            from .cognitive_coherence_engine import CognitiveCoherenceEngine  # noqa: PLC0415
            return CognitiveCoherenceEngine
        except ImportError as err:
            raise ImportError("CognitiveCoherence engine not found") from err

    raise AttributeError(f"module {__name__} has no attribute {name}")
