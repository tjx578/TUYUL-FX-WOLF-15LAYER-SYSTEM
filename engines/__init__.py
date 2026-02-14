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
        "momentum": FusionMomentumEngine(),
        "precision": FusionPrecisionEngine(),
        "structure": FusionStructureEngine(),
        "field": QuantumFieldEngine(),
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
    "QuantumAdvisoryEngine",
    "QuantumFieldEngine",
    "QuantumProbabilityEngine",
    "create_engine_suite",
]
