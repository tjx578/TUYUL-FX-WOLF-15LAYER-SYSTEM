"""Engine facade exports."""

from .quantum_advisory_engine import (
    AdvisorySignal,
    AdvisorySummary,
    QuantumAdvisoryEngine,
    RiskPosture,
)


def create_engine_suite() -> dict[str, object]:
    """Create engine suite map for integration points."""
    return {
        "advisory": QuantumAdvisoryEngine(),
    }


__all__ = [
    "AdvisorySignal",
    "AdvisorySummary",
    "QuantumAdvisoryEngine",
    "RiskPosture",
    "create_engine_suite",
]
