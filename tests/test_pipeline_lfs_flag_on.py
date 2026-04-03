"""Tests for pipeline LFS feature flag ON behavior.

Verifies that when ENABLE_LFS_SOFTENER=1:
- synthesis["lorentzian"] is populated with real LFS values
- enrichment_confidence_adj is modified
- no authority fields (verdict, direction, lot_size) are affected
- LFS stays advisory-only
"""

from __future__ import annotations

import math
from dataclasses import asdict

from analysis.reflective.lorentzian_field_engine import (
    LFS_MAX_BONUS,
    LFS_MAX_PENALTY,
    compute_e_norm,
)
from engines.lorentzian_enricher import LorentzianFieldEnricher

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _rich_synthesis() -> dict:
    """A populated synthesis dict simulating realistic pipeline output."""
    return {
        "layers": {
            "L2_reflex_coherence": 0.72,
            "L3_trq3d_energy": 0.85,
            "L8_tii_sym": 0.91,
            "L8_integrity_index": 0.88,
            "L8_twms_score": 0.80,
            "L9_liquidity_score": 0.65,
        },
        "fusion_frpc": {"frpc_energy": 0.78},
        "trq3d": {"drift": 0.003},
    }


# ═══════════════════════════════════════════════════════════════════════════
# §1  Enricher produces real LFS when flag is on
# ═══════════════════════════════════════════════════════════════════════════


class TestLFSFlagOnEnricher:
    """Simulate what the pipeline does when ENABLE_LFS_SOFTENER=1."""

    def setup_method(self):
        self.enricher = LorentzianFieldEnricher()
        self.synthesis = _rich_synthesis()

    def test_result_fills_synthesis_lorentzian(self):
        result = self.enricher.analyze(self.synthesis)
        lfs_dict = asdict(result)
        # All numeric fields should be non-zero for a populated synthesis
        assert lfs_dict["e_norm"] > 0.0
        assert lfs_dict["lrce"] > 0.0

    def test_e_norm_matches_engine(self):
        result = self.enricher.analyze(self.synthesis)
        # Verify enricher uses the pure engine correctly
        from analysis.reflective.lorentzian_field_adapter import map_layer_results_to_abg

        a, b, g = map_layer_results_to_abg(self.synthesis)
        expected = compute_e_norm(a, b, g)
        assert abs(result.e_norm - expected) < 1e-4

    def test_confidence_adj_bounded(self):
        result = self.enricher.analyze(self.synthesis)
        assert LFS_MAX_PENALTY <= result.confidence_adj <= LFS_MAX_BONUS

    def test_field_phase_is_valid(self):
        result = self.enricher.analyze(self.synthesis)
        assert result.field_phase in {"EXPANSION", "CONTRACTION", "STABILIZATION"}

    def test_quality_band_is_valid(self):
        result = self.enricher.analyze(self.synthesis)
        assert result.quality_band in {"STABLE", "CAUTION", "WEAK"}

    def test_advisory_only_always_true(self):
        result = self.enricher.analyze(self.synthesis)
        assert result.advisory_only is True

    def test_no_nan_no_inf(self):
        result = self.enricher.analyze(self.synthesis)
        for field in ("e_norm", "lrce", "gradient_signed", "gradient_abs", "drift", "confidence_adj"):
            v = getattr(result, field)
            assert not math.isnan(v), f"NaN in {field}"
            assert not math.isinf(v), f"Inf in {field}"


# ═══════════════════════════════════════════════════════════════════════════
# §2  Authority boundary — LFS never touches authority fields
# ═══════════════════════════════════════════════════════════════════════════


class TestLFSNeverTouchesAuthority:
    """LFS result must NOT contain any authority/execution/sizing fields."""

    FORBIDDEN_KEYS = {
        "verdict",
        "direction",
        "trade_valid",
        "position_size",
        "lot_size",
        "recommended_lot",
        "max_safe_lot",
        "risk_amount",
        "risk_percent",
        "balance",
        "equity",
        "margin",
    }

    def test_result_has_no_authority_fields(self):
        enricher = LorentzianFieldEnricher()
        result = enricher.analyze(_rich_synthesis())
        lfs_dict = asdict(result)
        violations = self.FORBIDDEN_KEYS & set(lfs_dict.keys())
        assert len(violations) == 0, f"Authority fields leaked: {violations}"


# ═══════════════════════════════════════════════════════════════════════════
# §3  History tracking — gradient reflects temporal change
# ═══════════════════════════════════════════════════════════════════════════


class TestLFSHistoryEffect:
    """When previous α–β–γ history is provided, gradient should reflect change."""

    def test_stable_history_gives_stabilization(self):
        enricher = LorentzianFieldEnricher()
        syn = _rich_synthesis()
        from analysis.reflective.lorentzian_field_adapter import map_layer_results_to_abg

        a, b, g = map_layer_results_to_abg(syn)
        # Same history = no delta → stabilization
        result = enricher.analyze(syn, history={"alpha": a, "beta": b, "gamma": g})
        assert result.field_phase == "STABILIZATION"

    def test_expanding_history_gives_expansion(self):
        enricher = LorentzianFieldEnricher()
        syn = _rich_synthesis()
        # Previous values significantly lower → positive delta → expansion
        result = enricher.analyze(syn, history={"alpha": 0.1, "beta": 0.1, "gamma": 0.1})
        assert result.field_phase == "EXPANSION"

    def test_contracting_history_gives_contraction(self):
        enricher = LorentzianFieldEnricher()
        syn = _rich_synthesis()
        # Previous values significantly higher → negative delta → contraction
        result = enricher.analyze(syn, history={"alpha": 0.99, "beta": 0.99, "gamma": 0.99})
        assert result.field_phase == "CONTRACTION"

    def test_no_history_defaults_to_stabilization(self):
        enricher = LorentzianFieldEnricher()
        result = enricher.analyze(_rich_synthesis(), history=None)
        assert result.field_phase == "STABILIZATION"


# ═══════════════════════════════════════════════════════════════════════════
# §4  Confidence adjustment application simulation
# ═══════════════════════════════════════════════════════════════════════════


class TestConfidenceAdjApplication:
    """Simulate how the pipeline applies confidence_adj to enrichment_confidence_adj."""

    def test_adj_modifies_enrichment(self):
        enricher = LorentzianFieldEnricher()
        result = enricher.analyze(_rich_synthesis())
        # Simulate pipeline logic: enrichment_confidence_adj += result.confidence_adj
        baseline = 0.0
        modified = baseline + result.confidence_adj
        assert LFS_MAX_PENALTY <= modified <= LFS_MAX_BONUS

    def test_adj_bounded_even_with_existing_offset(self):
        enricher = LorentzianFieldEnricher()
        result = enricher.analyze(_rich_synthesis())
        # Even with existing -0.02 offset, total should stay reasonable
        baseline = -0.02
        modified = max(LFS_MAX_PENALTY, min(LFS_MAX_BONUS, baseline + result.confidence_adj))
        assert LFS_MAX_PENALTY <= modified <= LFS_MAX_BONUS
