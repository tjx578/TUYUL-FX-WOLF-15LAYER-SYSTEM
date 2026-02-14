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
    return {
        "coherence": CognitiveCoherenceEngine(),
        "context": CognitiveContextEngine(),
        "risk": CognitiveRiskSimulation(),
        "field": QuantumFieldEngine(),
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
    "CoherenceState",
    "FusionMomentumEngine",
    "FusionPrecisionEngine",
    "FusionStructureEngine",
    "QuantumAdvisoryEngine",
    "QuantumFieldEngine",
    "QuantumProbabilityEngine",
    "create_engine_suite",
]
