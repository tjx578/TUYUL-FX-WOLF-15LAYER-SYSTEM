"""L5_psychology.py - Alias module for backward compatibility.

The authoritative implementation is in L5_psychology_fundamental.py.
This module re-exports everything from there for test/import compatibility.
"""  # noqa: N999

from analysis.layers.L5_psychology_fundamental import (  # noqa: F401
    L5AnalysisLayer,
    L5PsychologyAnalyzer,
    PsychGate,
    analyze_fundamental,
    analyze_l5,
)

__all__ = [
    "L5AnalysisLayer",
    "L5PsychologyAnalyzer",
    "PsychGate",
    "analyze_fundamental",
    "analyze_l5",
]
