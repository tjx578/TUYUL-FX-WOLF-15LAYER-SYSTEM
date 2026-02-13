"""
Wolf 15-Layer Reasoning Engine Package

This package provides the orchestration layer for the Wolf 15-Layer Analysis System.
It wraps and calls real analyzers while providing sequential halt, typed context,
execution logging, and template population.
"""

from reasoning.context import LayerResult, LayerState, Verdict, WolfContext, WolfStatus
from reasoning.engine import Wolf15LayerEngine

__all__ = [
    "Wolf15LayerEngine",
    "WolfContext",
    "LayerResult",
    "LayerState",
    "Verdict",
    "WolfStatus",
]
