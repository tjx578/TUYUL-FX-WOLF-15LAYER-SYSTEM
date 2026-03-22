"""Smoke tests for import chain integrity.

Verifies that all critical import paths resolve to real classes/functions
(not stubs) so silent runtime failures are caught early in CI.

Zone: tests/ -- read-only import validation, no execution side-effects.
"""

from __future__ import annotations

import importlib

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# §1  core.core_fusion_unified shim
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_core_fusion_unified_shim_importable() -> None:
    """``from core.core_fusion_unified import FusionIntegrator`` must resolve."""
    mod = importlib.import_module("core.core_fusion_unified")
    assert hasattr(mod, "FusionIntegrator"), "core.core_fusion_unified shim is missing FusionIntegrator"


@pytest.mark.smoke
def test_core_fusion_unified_shim_returns_real_class() -> None:
    """FusionIntegrator from shim must be a real class, not a stub."""
    from core.core_fusion_unified import FusionIntegrator

    assert isinstance(FusionIntegrator, type), "FusionIntegrator from shim is not a type"
    doc = getattr(FusionIntegrator, "__doc__", "") or ""
    assert "Stub:" not in doc, f"FusionIntegrator from shim resolved to a stub: {doc!r}"


@pytest.mark.smoke
def test_core_fusion_unified_shim_all_populated() -> None:
    """Shim __all__ must expose the same symbols as core.core_fusion, with identity."""
    import core.core_fusion as fusion_pkg
    import core.core_fusion_unified as shim

    for name in fusion_pkg.__all__:
        assert name in shim.__all__, f"core.core_fusion_unified shim is missing symbol: {name!r}"
        assert getattr(shim, name) is getattr(fusion_pkg, name), (
            f"core.core_fusion_unified.{name} is not the same object as core.core_fusion.{name}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# §2  core.core_fusion package
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_core_fusion_package_importable() -> None:
    """``from core.core_fusion import FusionIntegrator`` must work."""
    from core.core_fusion import FusionIntegrator

    assert isinstance(FusionIntegrator, type)


@pytest.mark.smoke
def test_core_import_fusion_integrator_is_real_class() -> None:
    """``from core import FusionIntegrator`` must resolve to a real class."""
    from core import FusionIntegrator

    assert isinstance(FusionIntegrator, type)
    doc = getattr(FusionIntegrator, "__doc__", "") or ""
    assert "Stub:" not in doc, f"core.FusionIntegrator is a stub: {doc!r}"


# ──────────────────────────────────────────────────────────────────────────────
# §3  All 4 core unified modules importable without crashing
# ──────────────────────────────────────────────────────────────────────────────

_CORE_UNIFIED_MODULES = [
    "core.core_cognitive_unified",
    "core.core_fusion_unified",  # shim (new)
    "core.core_quantum_unified",
    "core.core_reflective_unified",
]


@pytest.mark.smoke
@pytest.mark.parametrize("module_path", _CORE_UNIFIED_MODULES)
def test_core_unified_module_importable(module_path: str) -> None:
    """Each of the 4 core unified modules must import without crashing."""
    mod = importlib.import_module(module_path)
    assert mod is not None, f"{module_path} returned None"


# ──────────────────────────────────────────────────────────────────────────────
# §4  core/__init__.py _FUSION_SYMBOLS — all resolve to non-stub objects
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_fusion_symbols_all_non_stub() -> None:
    """Every symbol in core._FUSION_SYMBOLS must resolve to a real object."""
    import core
    from core import _FUSION_SYMBOLS  # type: ignore[attr-defined]

    stubs: list[str] = []
    for name in _FUSION_SYMBOLS:
        obj = getattr(core, name, None)
        if obj is None:
            stubs.append(f"{name} (missing)")
            continue
        doc = getattr(obj, "__doc__", "") or ""
        if "Stub:" in doc:
            stubs.append(f"{name} (stub)")

    assert not stubs, f"The following core fusion symbols are stubs or missing: {stubs}"


# ──────────────────────────────────────────────────────────────────────────────
# §5  analysis.layers.L7_L8_minimal path alias
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.smoke
def test_analysis_layers_l7_l8_minimal_importable() -> None:
    """``from analysis.layers.L7_L8_minimal import ...`` must work."""
    mod = importlib.import_module("analysis.layers.L7_L8_minimal")
    assert hasattr(mod, "L7MinimalAnalyzer"), "Missing L7MinimalAnalyzer"
    assert hasattr(mod, "L8PipelineAdapter"), "Missing L8PipelineAdapter"
    assert hasattr(mod, "get_l7_analyzer"), "Missing get_l7_analyzer"
    assert hasattr(mod, "get_l8_adapter"), "Missing get_l8_adapter"


@pytest.mark.smoke
def test_analysis_layers_l7_l8_minimal_classes_are_real() -> None:
    """Classes from analysis.layers.L7_L8_minimal must be real types."""
    from analysis.layers.L7_L8_minimal import L7MinimalAnalyzer, L8PipelineAdapter

    assert isinstance(L7MinimalAnalyzer, type)
    assert isinstance(L8PipelineAdapter, type)


@pytest.mark.smoke
def test_analysis_layers_l7_l8_minimal_same_as_core() -> None:
    """analysis.layers.L7_L8_minimal must re-export the same objects as core."""
    from analysis.layers import L7_L8_minimal as alias
    from core import L7_L8_minimal as canonical

    assert alias.L7MinimalAnalyzer is canonical.L7MinimalAnalyzer
    assert alias.L8PipelineAdapter is canonical.L8PipelineAdapter
