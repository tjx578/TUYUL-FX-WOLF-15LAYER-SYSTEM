"""
Analysis Orchestrators — position sizing bridge only.

Pipeline orchestration has been fully consolidated into:
    pipeline.WolfConstitutionalPipeline (v8.0 Unified Super Pipeline)

This package retains only the AnalysisRiskInput / DashboardRiskOutput
bridge for analysis → dashboard handoff (constitutional boundary).
"""

from analysis.orchestrators.position_sizing_bridge import (
    AnalysisRiskInput,
    DashboardRiskOutput,
    package_for_dashboard,
)

__all__ = ["AnalysisRiskInput", "DashboardRiskOutput", "package_for_dashboard"]
