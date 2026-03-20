"""
pipeline.phases — Phase-based modules for the Wolf Constitutional Pipeline.

This package splits wolf_constitutional_pipeline.py into focused,
testable phase modules:

    synthesis        - Phase 5: build_l12_synthesis (pure function)
    gates            - Phase 5: evaluate_9_gates (pure function)
    assembly         - Phase 8: build_l14_json (pure function)
    vault            - Phase 7: compute_vault_sync
    metrics_recorder - Prometheus metrics recording

All modules are pure analysis helpers with no execution authority.
Layer-12 remains the SOLE CONSTITUTIONAL AUTHORITY.
"""

from pipeline.phases.assembly import build_l14_json
from pipeline.phases.gates import evaluate_9_gates
from pipeline.phases.metrics_recorder import record_pipeline_metrics
from pipeline.phases.synthesis import build_l12_synthesis
from pipeline.phases.vault import compute_vault_sync

__all__ = [
    "build_l12_synthesis",
    "build_l14_json",
    "compute_vault_sync",
    "evaluate_9_gates",
    "record_pipeline_metrics",
]
