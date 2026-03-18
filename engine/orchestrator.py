"""Engine orchestrator placeholder."""

from pipeline.wolf_constitutional_pipeline import WolfConstitutionalPipeline


def build_orchestrator() -> WolfConstitutionalPipeline:
    """Construct the canonical engine orchestrator."""
    return WolfConstitutionalPipeline()
