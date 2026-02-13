"""
Wolf 15-Layer Reasoning Engine Package

This package provides the orchestration layer for the Wolf 15-Layer Analysis System.
It wraps and calls real analyzers while providing sequential halt, typed context,
execution logging, and template population.
"""

from reasoning.context import LayerResult, LayerState, Verdict, WolfContext, WolfStatus
from reasoning.engine import Wolf15LayerEngine
from reasoning.template import Wolf15LayerTemplatePopulator

__all__ = [
    "Wolf15LayerEngine",
    "Wolf15LayerTemplatePopulator",
    "WolfContext",
    "LayerResult",
    "LayerState",
    "Verdict",
    "WolfStatus",
]
