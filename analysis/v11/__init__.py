"""
V11 — Extreme Selectivity Gate (Analysis Zone)

Public API:
    V11PipelineHook  — drop-in hook for the analysis pipeline
    V11GateInput     — validated input model
    V11GateResult    — structured output model
    GateVerdict      — PASS / FAIL / SKIP enum
"""

from analysis.v11.data_adapter import V11DataAdapter
from analysis.v11.extreme_selectivity_gate import ExtremeSelectivityGateV11, V11Thresholds
from analysis.v11.models import GateVerdict, V11GateInput, V11GateResult
from analysis.v11.pipeline_hook import V11PipelineHook

__all__ = [
    "GateVerdict",
    "V11GateInput",
    "V11GateResult",
    "ExtremeSelectivityGateV11",
    "V11Thresholds",
    "V11DataAdapter",
    "V11PipelineHook",
]
