"""Engine facade package for TUYUL FX pipeline."""

from .cognitive_coherence_engine import CognitiveCoherenceEngine, CoherenceResult
from .cognitive_context_engine import CognitiveContextEngine, ContextResult
from .cognitive_risk_simulation import CognitiveRiskSimulation, RiskSimulationResult
from .fusion_momentum_engine import FusionMomentumEngine, MomentumResult
from .fusion_precision_engine import FusionPrecisionEngine, PrecisionResult
from .fusion_structure_engine import FusionStructureEngine, StructureResult
from .quantum_advisory_engine import AdvisorySummary, QuantumAdvisoryEngine
from .quantum_field_engine import FieldResult, QuantumFieldEngine
"""Engine package facade."""

from __future__ import annotations

from typing import Dict

from engines.quantum_field_engine import QuantumFieldEngine


def create_engine_suite() -> Dict[str, QuantumFieldEngine]:
    """Create default engine suite."""
    return {"field": QuantumFieldEngine()}


__all__ = ["QuantumFieldEngine", "create_engine_suite"]
"""Engine facade exports."""

"""Engine facade modules for market analysis."""

from .fusion_structure_engine import FusionStructure, FusionStructureEngine, StructureState

__all__ = [
    "FusionStructure",
    "FusionStructureEngine",
    "StructureState",
"""Engine facade package for TUYUL FX system."""

from .fusion_precision_engine import FusionPrecision, FusionPrecisionEngine


def create_engine_suite():
    """Create a minimal engine suite map."""
    return {
        "precision": FusionPrecisionEngine(),
    }


__all__ = ["FusionPrecision", "FusionPrecisionEngine", "create_engine_suite"]
"""Engine facade layer for TUYUL FX."""
"""Engine facade package."""

from .cognitive_coherence_engine import CognitiveCoherenceEngine, CoherenceState
from .cognitive_context_engine import CognitiveContextEngine
from .cognitive_risk_simulation import CognitiveRiskSimulation
from .fusion_momentum_engine import FusionMomentumEngine
from .fusion_precision_engine import FusionPrecisionEngine
from .fusion_structure_engine import FusionStructureEngine
from .quantum_advisory_engine import QuantumAdvisoryEngine
from .quantum_field_engine import QuantumFieldEngine
from .quantum_probability_engine import QuantumProbabilityEngine


def create_engine_suite():
    """Create a complete suite of all 9 engines with default configuration."""
"""Engine facade exports."""

from engines.cognitive_risk_simulation import CognitiveRiskSimulation, RiskSimulationResult

__all__ = ["CognitiveRiskSimulation", "RiskSimulationResult"]
"""Engine facade layer for pre-processing and cross-engine synthesis."""

from engines.cognitive_coherence_engine import CognitiveCoherenceEngine
from engines.cognitive_context_engine import CognitiveContextEngine
from engines.cognitive_risk_simulation import CognitiveRiskSimulation
from engines.fusion_momentum_engine import FusionMomentumEngine
from engines.fusion_precision_engine import FusionPrecisionEngine
from engines.fusion_structure_engine import FusionStructureEngine
from engines.quantum_advisory_engine import QuantumAdvisoryEngine
from engines.quantum_field_engine import QuantumFieldEngine
from engines.quantum_probability_engine import QuantumProbabilityEngine


def create_engine_suite() -> dict[str, object]:
    """Create a default suite with all optional engines ready to use."""
    return {
        "coherence": CognitiveCoherenceEngine(),
        "context": CognitiveContextEngine(),
        "risk": CognitiveRiskSimulation(),
        "field": QuantumFieldEngine(),
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

__version__ = "2.0.0"
__codename__ = "Wolf Engine Facade"

# --- Cognitive ---
from .cognitive_coherence_engine import (
    CoherenceGate,
    CognitiveCoherence,
    CognitiveCoherenceEngine,
    IntegrityStatus,
    ReflexState,
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
    FusionMomentum,
    FusionMomentumEngine,
    MomentumBand,
    MomentumPhase,
)
from .fusion_precision_engine import FusionPrecision, FusionPrecisionEngine
from .fusion_structure_engine import FusionStructure, FusionStructureEngine, StructureState

# --- Quantum ---
from .quantum_advisory_engine import (
    AdvisorySignal,
    AdvisorySummary,
    QuantumAdvisoryEngine,
    RiskPosture,
)


def create_engine_suite() -> dict[str, object]:
    """Create engine suite map for integration points."""
    return {
from .quantum_field_engine import QuantumFieldEngine
from .quantum_probability_engine import (
    DEFAULT_LAYER_WEIGHTS,
    ProbabilityResult,
    QuantumProbabilityEngine,
)


def create_engine_suite() -> dict[str, object]:
    """Create default engine instances for the facade layer."""
    return {
        "coherence": CognitiveCoherenceEngine(),
        "context": CognitiveContextEngine(),
        "risk": CognitiveRiskSimulation(),
        "momentum": FusionMomentumEngine(),
        "precision": FusionPrecisionEngine(),
        "structure": FusionStructureEngine(),
        "field": QuantumFieldEngine(),
def create_engine_suite() -> dict:
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
        "probability": QuantumProbabilityEngine(),
        "advisory": QuantumAdvisoryEngine(),
    }


__all__ = [
    "CognitiveCoherenceEngine",
    "CognitiveContextEngine",
    "CognitiveRiskSimulation",
    "FusionMomentumEngine",
    "FusionPrecisionEngine",
    "FusionStructureEngine",
    "AdvisorySummary",
    "CoherenceResult",
    "CognitiveCoherenceEngine",
    "CognitiveContextEngine",
    "CognitiveRiskSimulation",
    "CoherenceState",
    "FusionMomentumEngine",
    "FusionPrecisionEngine",
    "FusionStructureEngine",
    "ContextResult",
    "DEFAULT_LAYER_WEIGHTS",
    "FieldResult",
    "FusionMomentumEngine",
    "FusionPrecisionEngine",
    "FusionStructureEngine",
    "MomentumResult",
    "PrecisionResult",
    "ProbabilityResult",
    "QuantumAdvisoryEngine",
    "QuantumFieldEngine",
    "QuantumProbabilityEngine",
    "RiskSimulationResult",
    "StructureResult",
    "AdvisorySignal",
    "AdvisorySummary",
    "QuantumAdvisoryEngine",
    "RiskPosture",
    "CognitiveCoherenceEngine",
    "CognitiveContextEngine",
    "CognitiveRiskSimulation",
    "FusionMomentumEngine",
    "FusionPrecisionEngine",
    "FusionStructureEngine",
    "QuantumAdvisoryEngine",
    "QuantumFieldEngine",
    "QuantumProbabilityEngine",
    "QuantumFieldEngine",
    "QuantumProbabilityEngine",
    "QuantumAdvisoryEngine",
    "QuantumFieldEngine",
    "QuantumProbabilityEngine",
    "create_engine_suite",
]
