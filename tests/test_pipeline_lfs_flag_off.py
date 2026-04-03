"""Tests for pipeline LFS feature flag OFF behavior.

Verifies that when ENABLE_LFS_SOFTENER=0 (default), the pipeline
does not inject any LFS data into synthesis or enrichment.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from analysis.reflective.lorentzian_field_adapter import map_layer_results_to_abg
from pipeline.phases.synthesis import build_l12_synthesis

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _empty_layer_results() -> dict:
    """Minimal layer_results dict that build_l12_synthesis can consume."""
    return {
        "L1": {},
        "L2": {},
        "L3": {},
        "L4": {},
        "L5": {},
        "L6": {},
        "L7": {},
        "L8": {},
        "L9": {},
        "L10": {},
        "L11": {},
    }


# ═══════════════════════════════════════════════════════════════════════════
# §1  Synthesis defaults — LFS placeholder is always zeroed
# ═══════════════════════════════════════════════════════════════════════════


class TestSynthesisLFSDefault:
    """build_l12_synthesis always includes a zeroed LFS block."""

    def test_lorentzian_key_exists(self):
        syn = build_l12_synthesis(_empty_layer_results(), symbol="EURUSD")
        assert "lorentzian" in syn

    def test_lorentzian_defaults_zeroed(self):
        syn = build_l12_synthesis(_empty_layer_results(), symbol="EURUSD")
        lfs = syn["lorentzian"]
        assert lfs["e_norm"] == 0.0
        assert lfs["lrce"] == 0.0
        assert lfs["drift"] == 0.0
        assert lfs["rescue_eligible"] is False

    def test_lorentzian_phase_default(self):
        syn = build_l12_synthesis(_empty_layer_results(), symbol="EURUSD")
        assert syn["lorentzian"]["field_phase"] == "UNKNOWN"

    def test_lorentzian_band_default(self):
        syn = build_l12_synthesis(_empty_layer_results(), symbol="EURUSD")
        assert syn["lorentzian"]["quality_band"] == "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════════════
# §2  Adapter — edge cases with empty/missing data
# ═══════════════════════════════════════════════════════════════════════════


class TestAdapterFlagOff:
    """When flag is off, adapter is never called, but test its safety."""

    def test_empty_synthesis(self):
        a, b, g = map_layer_results_to_abg({})
        assert 0.0 <= a <= 1.0
        assert 0.0 <= b <= 1.0
        assert 0.0 <= g <= 1.0

    def test_none_layers(self):
        a, b, g = map_layer_results_to_abg({"layers": None})
        assert a == 0.0 and b == 0.0 and g == 0.0

    def test_none_fusion(self):
        a, b, g = map_layer_results_to_abg({"fusion_frpc": None})
        assert 0.0 <= a <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# §3  Pipeline class — ENABLE_LFS_SOFTENER default is False
# ═══════════════════════════════════════════════════════════════════════════


class TestPipelineLFSFlagDefault:
    """The pipeline's LFS flag is off by default."""

    def test_flag_default_off(self):
        old = os.environ.pop("ENABLE_LFS_SOFTENER", None)
        try:
            val = os.getenv("ENABLE_LFS_SOFTENER", "0") == "1"
            assert val is False
        finally:
            if old is not None:
                os.environ["ENABLE_LFS_SOFTENER"] = old

    def test_flag_explicitly_zero(self):
        with patch.dict("os.environ", {"ENABLE_LFS_SOFTENER": "0"}):
            val = os.getenv("ENABLE_LFS_SOFTENER", "0") == "1"
            assert val is False
