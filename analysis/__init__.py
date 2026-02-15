"""
Analysis Package -- Wolf-15 Layer System (L1-L11)
=================================================

Pure analysis zone.  **No execution side-effects allowed.**

Sub-packages
------------
layers/      Individual layer analyzers (L1-Context ... L11-RR).
macro/       Macro regime engines -- VIX, volatility, monthly regime.
market/      Market-structure helpers -- Fibonacci, indicators, S/D.
orchestrators/  Position sizing bridge (analysis -> dashboard handoff).

Top-level modules
-----------------
data_feed           Real-time tick feed adapter with staleness detection.
l6_risk             L6 drawdown-tier risk analysis (``analyze_risk``).
l8_tii              L8 TII integrity + TWMS scoring (``analyze_tii``).
synthesis_contract  Immutable output contract for L12/L14 export.

Backward-compatible re-exports
------------------------------
Historical flat imports (``analysis.vix_analysis_engine``, etc.) are
re-exported here so existing call-sites keep working.  **Prefer the
canonical paths** (``analysis.macro.vix_analysis_engine``, ...).
"""

from __future__ import annotations

from analysis.macro.macro_regime_engine import MacroRegimeEngine as MacroRegimeEngine

# ── Canonical sub-package imports (lazy / backward-compat) ───────────
# These allow  ``from analysis.vix_analysis_engine import ...``  to keep
# working even though the modules now live under analysis/macro/.
from analysis.macro.vix_analysis_engine import VIXAnalysisEngine as VIXAnalysisEngine
from analysis.macro.vix_analysis_engine import VIXState as VIXState
from analysis.macro.vix_proxy_estimator import VIXProxyEstimator as VIXProxyEstimator
from analysis.macro.vix_proxy_estimator import VIXProxyState as VIXProxyState
from analysis.macro.volatility import calculate_atr as calculate_atr
from analysis.macro.volatility import volatility_regime as volatility_regime

__all__ = [
    "MacroRegimeEngine",
    # Macro re-exports
    "VIXAnalysisEngine",
    "VIXProxyEstimator",
    "VIXProxyState",
    "VIXState",
    "calculate_atr",
    # Sub-packages
    "layers", # type: ignore
    "macro", # pyright: ignore[reportUnsupportedDunderAll]
    "market", # pyright: ignore[reportUnsupportedDunderAll]
    "orchestrators", # pyright: ignore[reportUnsupportedDunderAll]
    "volatility_regime",
]
