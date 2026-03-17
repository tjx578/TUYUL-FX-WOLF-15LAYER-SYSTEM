"""
TUYUL FX - Engine Facade Layer v2.0 (Lazy Imports)

9 focused analysis engines that provide clean, testable API
over the monolithic core unified modules.

All imports are LAZY: importing `engines` does NOT trigger loading
any engine module.  Each class/function is resolved on first access
via ``__getattr__``.  This means a broken engine file only affects
code that actually uses that engine — no cascade failures.

Architecture:
  Cognitive Domain (internal state awareness):
    - CognitiveCoherenceEngine  -> emotion/reflex/integrity
    - CognitiveContextEngine    -> regime/structure/liquidity
    - CognitiveRiskSimulation   -> stress testing/tail risk

  Fusion Domain (technical analysis fusion):
    - FusionMomentumEngine      -> momentum/phase/TRQ energy
    - FusionPrecisionEngine     -> precision weights/EMA alignment
    - FusionStructureEngine     -> divergence/liquidity/MTF

  Quantum Domain (probabilistic analysis):
    - QuantumFieldEngine        -> field energy/bias/stability
    - QuantumProbabilityEngine  -> layer probability/uncertainty
    - QuantumAdvisoryEngine     -> cross-engine synthesis

Usage:
    from engines import create_engine_suite
    suite = create_engine_suite()
    # ... use suite["coherence"].evaluate(state)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__version__ = "2.0.0"
__codename__ = "Wolf Engine Facade"

if TYPE_CHECKING:
    from . import v11 as v11  # noqa: F401  # expose sub-package for static analysis
    from .cognitive_context_engine import (
        InstitutionalPresence,
        LiquidityContext,
        MarketRegime,
        MarketStructure,
    )
    from .cognitive_risk_simulation import RiskSimulationResult
    from .fusion_momentum_engine import MomentumResult
    from .fusion_precision_engine import PrecisionResult
    from .fusion_structure_engine import (
        FusionStructureEngine,
        StructureResult,
        StructureState,
    )
    from .quantum_advisory_engine import QuantumAdvisoryEngine
    from .quantum_field_engine import QuantumFieldEngine
    from .quantum_probability_engine import (
        ProbabilityResult,
        QuantumProbabilityEngine,
    )

    FusionStructure = StructureResult

# ---------------------------------------------------------------------------
# Lazy-import registry: name → (module_relative_path, real_name | None)
#   If real_name is None, the attribute name IS the symbol name in that module.
# ---------------------------------------------------------------------------
_LAZY_IMPORTS: dict[str, tuple[str, str | None]] = {
    # --- Cognitive ---
    "CognitiveCoherenceEngine": (".cognitive_coherence_engine", None),
    "CoherenceSnapshot": (".cognitive_coherence_engine", None),
    "CoherenceState": (".cognitive_coherence_engine", None),
    "CognitiveContextEngine": (".cognitive_context_engine", None),
    "CognitiveContext": (".cognitive_context_engine", None),
    "InstitutionalPresence": (".cognitive_context_engine", None),
    "LiquidityContext": (".cognitive_context_engine", None),
    "MarketRegime": (".cognitive_context_engine", None),
    "MarketStructure": (".cognitive_context_engine", None),
    "CognitiveRiskSimulation": (".cognitive_risk_simulation", None),
    "RiskSimulationResult": (".cognitive_risk_simulation", None),
    # --- Fusion ---
    "FusionMomentumEngine": (".fusion_momentum_engine", None),
    "MomentumResult": (".fusion_momentum_engine", None),
    "FusionPrecisionEngine": (".fusion_precision_engine", None),
    "PrecisionResult": (".fusion_precision_engine", None),
    "FusionStructureEngine": (".fusion_structure_engine", None),
    "StructureResult": (".fusion_structure_engine", None),
    "StructureState": (".fusion_structure_engine", None),
    # --- Quantum ---
    "QuantumAdvisoryEngine": (".quantum_advisory_engine", None),
    "AdvisoryResult": (".quantum_advisory_engine", None),
    "AdvisorySignal": (".quantum_advisory_engine", None),
    "QuantumFieldEngine": (".quantum_field_engine", None),
    "FieldResult": (".quantum_field_engine", None),
    "QuantumProbabilityEngine": (".quantum_probability_engine", None),
    "ProbabilityResult": (".quantum_probability_engine", None),
}

# Backward-compat aliases: resolved lazily via the same mechanism.
_LAZY_ALIASES: dict[str, str] = {
    "CognitiveCoherence": "CoherenceSnapshot",
    "FusionMomentum": "MomentumResult",
    "FusionPrecision": "PrecisionResult",
    "FusionStructure": "StructureResult",
}

__all__ = [
    # Quantum types
    "AdvisoryResult",  # pyright: ignore[reportUnsupportedDunderAll]
    # Backward-compat aliases
    "AdvisorySignal",  # pyright: ignore[reportUnsupportedDunderAll]
    "CognitiveCoherence",  # pyright: ignore[reportUnsupportedDunderAll]
    # Cognitive engines
    "CognitiveCoherenceEngine",  # pyright: ignore[reportUnsupportedDunderAll]
    "CognitiveContextEngine",  # pyright: ignore[reportUnsupportedDunderAll]
    "CognitiveRiskSimulation",  # pyright: ignore[reportUnsupportedDunderAll]
    # Cognitive types
    "CoherenceSnapshot",  # pyright: ignore[reportUnsupportedDunderAll]
    "CoherenceState",  # pyright: ignore[reportUnsupportedDunderAll]
    "FieldResult",  # pyright: ignore[reportUnsupportedDunderAll]
    "FusionMomentum",  # pyright: ignore[reportUnsupportedDunderAll]
    # Fusion engines
    "FusionMomentumEngine",  # pyright: ignore[reportUnsupportedDunderAll]
    "FusionPrecision",  # pyright: ignore[reportUnsupportedDunderAll]
    "FusionPrecisionEngine",  # pyright: ignore[reportUnsupportedDunderAll]
    "FusionStructure",
    "FusionStructureEngine",
    "InstitutionalPresence",
    "LiquidityContext",
    "MarketRegime",
    "MarketStructure",
    # Fusion types
    "MomentumResult",
    "PrecisionResult",
    "ProbabilityResult",
    # Quantum engines
    "QuantumAdvisoryEngine",
    "QuantumFieldEngine",
    "QuantumProbabilityEngine",
    "RiskSimulationResult",
    "StructureResult",
    "StructureState",
    # Factory
    "create_engine_suite",
]


# ---------------------------------------------------------------------------
# Module-level __getattr__  — the heart of lazy loading
# ---------------------------------------------------------------------------
def __getattr__(name: str):
    # 1. Direct lazy import
    if name in _LAZY_IMPORTS:
        mod_path, real_name = _LAZY_IMPORTS[name]
        import importlib  # noqa: PLC0415

        mod = importlib.import_module(mod_path, __name__)
        attr = getattr(mod, real_name or name)
        # Cache on module dict so __getattr__ is not called again
        globals()[name] = attr
        return attr

    # 2. Backward-compat aliases
    if name in _LAZY_ALIASES:
        target = _LAZY_ALIASES[name]
        attr = __getattr__(target)  # recursively resolve
        globals()[name] = attr
        return attr

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Factory function (also lazy — engines are only imported when called)
# ---------------------------------------------------------------------------
def create_engine_suite() -> dict[str, object]:
    """Factory: create all 9 engines with default configuration.

    Returns:
        Dict of engine_name -> engine_instance

    Each engine is imported on demand via ``__getattr__``.  If a specific
    engine module has an error, only *that* key is skipped — the rest
    still load successfully.
    """
    _map: dict[str, str] = {
        "coherence": "CognitiveCoherenceEngine",
        "context": "CognitiveContextEngine",
        "risk_sim": "CognitiveRiskSimulation",
        "risk": "CognitiveRiskSimulation",
        "momentum": "FusionMomentumEngine",
        "precision": "FusionPrecisionEngine",
        "structure": "FusionStructureEngine",
        "field": "QuantumFieldEngine",
        "probability": "QuantumProbabilityEngine",
        "advisory": "QuantumAdvisoryEngine",
    }

    suite: dict[str, object] = {}
    for key, cls_name in _map.items():
        try:
            cls = __getattr__(cls_name)
            suite[key] = cls()
        except Exception as exc:
            import logging  # noqa: PLC0415

            logging.getLogger(__name__).warning(
                "Engine %r (%s) skipped: %s",
                key,
                cls_name,
                exc,
            )
    return suite
