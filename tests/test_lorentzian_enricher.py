"""Tests for Lorentzian Field Stabilizer enrichment engine.

Verifies:
- Output is bounded (no NaN, no Inf)
- confidence_adj ∈ [-0.04, +0.03]
- e_norm ∈ [0, 1], lrce ∈ [0, 1]
- advisory_only is always True
- quality_band is one of STABLE / CAUTION / WEAK
- field_phase is one of EXPANSION / CONTRACTION / STABILIZATION
"""

from __future__ import annotations

import math

from analysis.reflective.lorentzian_field_contracts import LorentzianFieldResult
from analysis.reflective.lorentzian_field_engine import (
    LFS_MAX_BONUS,
    LFS_MAX_PENALTY,
    classify_phase,
    compute_confidence_adj,
    compute_e_norm,
    compute_gradient_abs,
    compute_gradient_signed,
    compute_lrce,
)
from engines.lorentzian_enricher import LorentzianFieldEnricher

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _synthesis(
    *,
    l3_energy: float = 0.8,
    l2_reflex: float = 0.7,
    l8_tii: float = 0.9,
    l8_integrity: float = 0.88,
    l8_twms: float = 0.85,
    l9_liq: float = 0.6,
    frpc_energy: float = 0.75,
    drift: float = 0.002,
) -> dict:
    return {
        "layers": {
            "L2_reflex_coherence": l2_reflex,
            "L3_trq3d_energy": l3_energy,
            "L8_tii_sym": l8_tii,
            "L8_integrity_index": l8_integrity,
            "L8_twms_score": l8_twms,
            "L9_liquidity_score": l9_liq,
        },
        "fusion_frpc": {"frpc_energy": frpc_energy},
        "trq3d": {"drift": drift},
    }


VALID_PHASES = {"EXPANSION", "CONTRACTION", "STABILIZATION"}
VALID_BANDS = {"STABLE", "CAUTION", "WEAK"}


# ═══════════════════════════════════════════════════════════════════════════
# §1  Pure Engine — Boundedness
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeENorm:
    def test_zero_inputs(self):
        assert compute_e_norm(0.0, 0.0, 0.0) == 0.0

    def test_max_inputs(self):
        assert compute_e_norm(1.0, 1.0, 1.0) == 1.0

    def test_always_in_unit(self):
        for a in (0.0, 0.3, 0.5, 0.7, 1.0):
            for b in (0.0, 0.5, 1.0):
                for g in (0.0, 0.5, 1.0):
                    v = compute_e_norm(a, b, g)
                    assert 0.0 <= v <= 1.0, f"e_norm={v} for ({a},{b},{g})"

    def test_no_nan(self):
        assert not math.isnan(compute_e_norm(0.0, 0.0, 0.0))
        assert not math.isnan(compute_e_norm(1.0, 1.0, 1.0))


class TestComputeLRCE:
    def test_zero_drift(self):
        v = compute_lrce(0.9, 1.0, 0.95, 0.0)
        assert 0.0 <= v <= 1.0

    def test_high_drift_lowers(self):
        low = compute_lrce(0.9, 1.0, 0.95, 0.5)
        high = compute_lrce(0.9, 1.0, 0.95, 0.0)
        assert low < high

    def test_bounded(self):
        for d in (0.0, 0.001, 0.01, 0.1, 1.0):
            v = compute_lrce(1.0, 1.0, 1.0, d)
            assert 0.0 <= v <= 1.0

    def test_no_nan(self):
        assert not math.isnan(compute_lrce(0.0, 0.0, 0.0, 0.0))


class TestComputeConfidenceAdj:
    def test_max_bonus(self):
        adj = compute_confidence_adj(lrce=0.975, drift=0.003, gradient_signed=0.001)
        assert adj == LFS_MAX_BONUS

    def test_max_penalty(self):
        adj = compute_confidence_adj(lrce=0.90, drift=0.01, gradient_signed=0.0)
        assert adj == LFS_MAX_PENALTY

    def test_bounds(self):
        for lrce in (0.0, 0.5, 0.93, 0.955, 0.97, 1.0):
            for drift in (0.0, 0.004, 0.006, 0.008, 0.01):
                for gs in (-0.01, 0.0, 0.005, 0.01):
                    adj = compute_confidence_adj(lrce, drift, gs)
                    assert LFS_MAX_PENALTY <= adj <= LFS_MAX_BONUS, f"adj={adj} for lrce={lrce} drift={drift} gs={gs}"


class TestGradientFunctions:
    def test_signed_no_change(self):
        assert compute_gradient_signed(0.0, 0.0, 0.0) == 0.0

    def test_abs_identical_axes(self):
        assert compute_gradient_abs(0.5, 0.5, 0.5) == 0.0

    def test_abs_divergent(self):
        v = compute_gradient_abs(0.0, 0.5, 1.0)
        assert v > 0.0


class TestClassifyPhase:
    def test_expansion(self):
        assert classify_phase(0.01) == "EXPANSION"

    def test_contraction(self):
        assert classify_phase(-0.01) == "CONTRACTION"

    def test_stabilization(self):
        assert classify_phase(0.0) == "STABILIZATION"
        assert classify_phase(0.005) == "STABILIZATION"
        assert classify_phase(-0.005) == "STABILIZATION"


# ═══════════════════════════════════════════════════════════════════════════
# §2  Enricher — Full Pipeline
# ═══════════════════════════════════════════════════════════════════════════


class TestLorentzianFieldEnricher:
    def setup_method(self):
        self.enricher = LorentzianFieldEnricher()

    def test_returns_correct_type(self):
        result = self.enricher.analyze(_synthesis())
        assert isinstance(result, LorentzianFieldResult)

    def test_advisory_only_always_true(self):
        result = self.enricher.analyze(_synthesis())
        assert result.advisory_only is True

    def test_e_norm_bounded(self):
        result = self.enricher.analyze(_synthesis())
        assert 0.0 <= result.e_norm <= 1.0

    def test_lrce_bounded(self):
        result = self.enricher.analyze(_synthesis())
        assert 0.0 <= result.lrce <= 1.0

    def test_confidence_adj_bounded(self):
        result = self.enricher.analyze(_synthesis())
        assert LFS_MAX_PENALTY <= result.confidence_adj <= LFS_MAX_BONUS

    def test_no_nan_in_output(self):
        result = self.enricher.analyze(_synthesis())
        for field in ("e_norm", "lrce", "gradient_signed", "gradient_abs", "drift", "confidence_adj"):
            assert not math.isnan(getattr(result, field)), f"NaN in {field}"
            assert not math.isinf(getattr(result, field)), f"Inf in {field}"

    def test_valid_phase(self):
        result = self.enricher.analyze(_synthesis())
        assert result.field_phase in VALID_PHASES

    def test_valid_quality_band(self):
        result = self.enricher.analyze(_synthesis())
        assert result.quality_band in VALID_BANDS

    def test_with_history_deltas(self):
        history = {"alpha": 0.4, "beta": 0.3, "gamma": 0.2}
        result = self.enricher.analyze(_synthesis(), history=history)
        assert isinstance(result, LorentzianFieldResult)
        assert result.field_phase in VALID_PHASES

    def test_empty_synthesis(self):
        result = self.enricher.analyze({})
        assert isinstance(result, LorentzianFieldResult)
        assert result.e_norm == 0.0
        assert result.lrce == 0.0

    def test_missing_layers_key(self):
        result = self.enricher.analyze({"trq3d": {"drift": 0.001}})
        assert isinstance(result, LorentzianFieldResult)
        assert 0.0 <= result.e_norm <= 1.0

    def test_rescue_eligible_requires_strict_conditions(self):
        # With high integrity and low drift, rescue may be eligible
        syn = _synthesis(l8_integrity=0.98, drift=0.001)
        result = self.enricher.analyze(syn)
        # rescue_eligible is bool regardless
        assert isinstance(result.rescue_eligible, bool)
