"""
V11 Hyper-Precision Sniper Engine Suite

Post-pipeline overlay for extreme selectivity filtering.
v11 can ONLY block trades (veto EXECUTE), never override HOLD.
L12 Constitutional Authority is PRESERVED.

Usage:
    from engines.v11 import V11PipelineHook

    hook = V11PipelineHook()
    overlay = hook.evaluate(pipeline_result, symbol="EURUSD", timeframe="H1")

    if overlay.should_trade:
        # Execute trade
        pass
"""

# Core components
from engines.v11.config import get_v11, is_v11_enabled
from engines.v11.data_adapter import V11DataAdapter
from engines.v11.exhaustion_detector import ExhaustionDetector, ExhaustionResult, ExhaustionState
from engines.v11.exhaustion_dvg_fusion import ExhaustionDVGFusion, ExhaustionDVGResult
from engines.v11.extreme_selectivity_gate import (
    ConfidenceBand,
    ExtremeGateInput,
    ExtremeGateResult,
    ExtremeSelectivityGateV11,
    GateVerdict,
)
from engines.v11.liquidity_sweep_scorer import LiquiditySweepResult, LiquiditySweepScorer
from engines.v11.pipeline_hook import V11Overlay, V11PipelineHook

# Portfolio
from engines.v11.portfolio import PortfolioDecision, SniperOptimizer

# Regime AI
from engines.v11.regime_ai import FeatureExtractor, OnlineKMeans, RegimeService

# Validation
from engines.v11.validation import EdgeValidationResult, EdgeValidator

__all__ = [
    # Config
    "get_v11",
    "is_v11_enabled",
    # Exhaustion
    "ExhaustionDetector",
    "ExhaustionResult",
    "ExhaustionState",
    # DVG Fusion
    "ExhaustionDVGFusion",
    "ExhaustionDVGResult",
    # Liquidity Sweep
    "LiquiditySweepScorer",
    "LiquiditySweepResult",
    # Extreme Gate
    "ExtremeSelectivityGateV11",
    "ExtremeGateInput",
    "ExtremeGateResult",
    "GateVerdict",
    "ConfidenceBand",
    # Data Adapter
    "V11DataAdapter",
    # Pipeline Hook
    "V11PipelineHook",
    "V11Overlay",
    # Regime AI
    "OnlineKMeans",
    "FeatureExtractor",
    "RegimeService",
    # Portfolio
    "SniperOptimizer",
    "PortfolioDecision",
    # Validation
    "EdgeValidator",
    "EdgeValidationResult",
]
