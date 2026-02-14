"""Engine facade package for TUYUL FX pipeline."""

from .cognitive_coherence_engine import CognitiveCoherenceEngine, CoherenceResult
from .cognitive_context_engine import CognitiveContextEngine, ContextResult
from .cognitive_risk_simulation import CognitiveRiskSimulation, RiskSimulationResult
from .fusion_momentum_engine import FusionMomentumEngine, MomentumResult
from .fusion_precision_engine import FusionPrecisionEngine, PrecisionResult
from .fusion_structure_engine import FusionStructureEngine, StructureResult
from .quantum_advisory_engine import AdvisorySummary, QuantumAdvisoryEngine
from .quantum_field_engine import FieldResult, QuantumFieldEngine
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
        "probability": QuantumProbabilityEngine(),
        "advisory": QuantumAdvisoryEngine(),
    }


__all__ = [
    "AdvisorySummary",
    "CoherenceResult",
    "CognitiveCoherenceEngine",
    "CognitiveContextEngine",
    "CognitiveRiskSimulation",
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
    "create_engine_suite",
]
