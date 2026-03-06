"""Tests for Multi-Timeframe RQI Sync (analysis/reflex_multitf.py)."""

from __future__ import annotations

import math

from analysis.reflex_multitf import (
    DEFAULT_TF_WEIGHTS,
    aggregate_multitf_rqi,
    compute_multitf_rqi,
    compute_per_tf_rqi,
    per_tf_coherence,
)

# ── Per-TF coherence derivation ──────────────────────────────────────────────


class TestPerTfCoherence:
    def test_neutral_is_zero(self) -> None:
        """p_bull=0.5 → zero conviction."""
        assert math.isclose(per_tf_coherence(0.5), 0.0)

    def test_full_bull_is_one(self) -> None:
        """p_bull=1.0 → full conviction."""
        assert math.isclose(per_tf_coherence(1.0), 1.0)

    def test_full_bear_is_one(self) -> None:
        """p_bull=0.0 → full conviction (bearish)."""
        assert math.isclose(per_tf_coherence(0.0), 1.0)

    def test_moderate_bull(self) -> None:
        """p_bull=0.7 → |0.7-0.5|*2 = 0.4"""
        assert math.isclose(per_tf_coherence(0.7), 0.4, rel_tol=1e-6)

    def test_moderate_bear(self) -> None:
        """p_bull=0.3 → |0.3-0.5|*2 = 0.4"""
        assert math.isclose(per_tf_coherence(0.3), 0.4, rel_tol=1e-6)

    def test_symmetric(self) -> None:
        """Bull and bear at equal distance from 0.5 give same coherence."""
        assert math.isclose(
            per_tf_coherence(0.8), per_tf_coherence(0.2),
        )


# ── Per-TF RQI computation ───────────────────────────────────────────────────


class TestComputePerTfRqi:
    def test_basic_computation(self) -> None:
        per_tf = {
            "M15": {"p_bull": 0.7},
            "H1": {"p_bull": 0.9},
            "H4": {"p_bull": 0.95},
        }
        result = compute_per_tf_rqi(per_tf, delta_t_sec=0.0, emotion_delta=0.0)
        # dt=0 → decay=1.0, emotion=0 → stability=1.0
        # M15: coh=0.4 → RQI=0.4
        # H1: coh=0.8 → RQI=0.8
        # H4: coh=0.9 → RQI=0.9
        assert math.isclose(result["M15"], 0.4, rel_tol=1e-4)
        assert math.isclose(result["H1"], 0.8, rel_tol=1e-4)
        assert math.isclose(result["H4"], 0.9, rel_tol=1e-4)

    def test_emotion_delta_penalty(self) -> None:
        per_tf = {"H1": {"p_bull": 0.9}}  # coh=0.8
        result = compute_per_tf_rqi(per_tf, delta_t_sec=0.0, emotion_delta=0.5)
        # RQI = 1.0 * 0.8 * 0.5 = 0.4
        assert math.isclose(result["H1"], 0.4, rel_tol=1e-4)

    def test_latency_penalty(self) -> None:
        per_tf = {"H1": {"p_bull": 1.0}}  # coh=1.0
        fresh = compute_per_tf_rqi(per_tf, delta_t_sec=0.0, emotion_delta=0.0)
        aged = compute_per_tf_rqi(per_tf, delta_t_sec=120.0, emotion_delta=0.0, sigma_sec=60.0)
        assert aged["H1"] < fresh["H1"]

    def test_empty_input(self) -> None:
        result = compute_per_tf_rqi({}, delta_t_sec=0.0, emotion_delta=0.0)
        assert result == {}

    def test_missing_p_bull_defaults_neutral(self) -> None:
        per_tf = {"H1": {"slope": 0.5}}  # no p_bull
        result = compute_per_tf_rqi(per_tf, delta_t_sec=0.0, emotion_delta=0.0)
        # defaults to p_bull=0.5 → coh=0 → rqi=0
        assert math.isclose(result["H1"], 0.0)


# ── Weighted aggregation ─────────────────────────────────────────────────────


class TestAggregateMultitfRqi:
    def test_user_spec_scenario(self) -> None:
        """Reproduce the user's spec example:
        M15=0.60, H1=0.88, H4=0.92
        Weights: M15=0.2, H1=0.5, H4=0.3
        Expected: 0.12 + 0.44 + 0.276 = 0.836
        """
        rqi_per_tf = {"M15": 0.60, "H1": 0.88, "H4": 0.92}
        result = aggregate_multitf_rqi(rqi_per_tf)
        assert math.isclose(result, 0.836, rel_tol=1e-3)

    def test_all_zero(self) -> None:
        rqi_per_tf = {"M15": 0.0, "H1": 0.0, "H4": 0.0}
        assert aggregate_multitf_rqi(rqi_per_tf) == 0.0

    def test_all_one(self) -> None:
        rqi_per_tf = {"M15": 1.0, "H1": 1.0, "H4": 1.0}
        assert math.isclose(aggregate_multitf_rqi(rqi_per_tf), 1.0)

    def test_partial_timeframes_renormalize(self) -> None:
        """Only H1 available → result = H1 value."""
        rqi_per_tf = {"H1": 0.75}
        result = aggregate_multitf_rqi(rqi_per_tf)
        assert math.isclose(result, 0.75)

    def test_two_of_three_renormalize(self) -> None:
        """H1 + H4 available (weights 0.5 + 0.3 = 0.8, normalized)."""
        rqi_per_tf = {"H1": 0.80, "H4": 0.90}
        # (0.5*0.8 + 0.3*0.9) / 0.8 = (0.40 + 0.27) / 0.8 = 0.8375
        result = aggregate_multitf_rqi(rqi_per_tf)
        assert math.isclose(result, 0.8375, rel_tol=1e-4)

    def test_no_overlap_returns_zero(self) -> None:
        rqi_per_tf = {"D1": 0.90}  # D1 not in default weights
        result = aggregate_multitf_rqi(rqi_per_tf)
        assert result == 0.0

    def test_custom_weights(self) -> None:
        rqi_per_tf = {"M5": 0.50, "M15": 0.80}
        weights = {"M5": 0.3, "M15": 0.7}
        result = aggregate_multitf_rqi(rqi_per_tf, tf_weights=weights)
        # (0.3*0.5 + 0.7*0.8) / 1.0 = 0.15 + 0.56 = 0.71
        assert math.isclose(result, 0.71, rel_tol=1e-4)

    def test_m15_noisy_h1_h4_strong(self) -> None:
        """M15 is LOCK territory, H1+H4 strong → CAUTION not LOCK."""
        rqi_per_tf = {"M15": 0.30, "H1": 0.88, "H4": 0.92}
        result = aggregate_multitf_rqi(rqi_per_tf)
        # 0.2*0.30 + 0.5*0.88 + 0.3*0.92 = 0.06 + 0.44 + 0.276 = 0.776
        assert math.isclose(result, 0.776, rel_tol=1e-3)
        # In CAUTION band [0.70, 0.85), not LOCK
        assert result >= 0.70


# ── End-to-end convenience function ──────────────────────────────────────────


class TestComputeMultitfRqi:
    def test_returns_all_fields(self) -> None:
        per_tf = {
            "M15": {"p_bull": 0.7},
            "H1": {"p_bull": 0.9},
            "H4": {"p_bull": 0.95},
        }
        result = compute_multitf_rqi(per_tf, delta_t_sec=0.0, emotion_delta=0.0)
        assert "rqi_per_tf" in result
        assert "rqi_multi" in result
        assert "tf_weights_used" in result
        assert isinstance(result["rqi_multi"], float)
        assert 0.0 <= result["rqi_multi"] <= 1.0

    def test_empty_per_tf(self) -> None:
        result = compute_multitf_rqi({}, delta_t_sec=0.0, emotion_delta=0.0)
        assert result["rqi_multi"] == 0.0
        assert result["rqi_per_tf"] == {}

    def test_default_weights_match(self) -> None:
        per_tf = {"H1": {"p_bull": 0.8}}
        result = compute_multitf_rqi(per_tf, delta_t_sec=0.0, emotion_delta=0.0)
        assert result["tf_weights_used"] == DEFAULT_TF_WEIGHTS
