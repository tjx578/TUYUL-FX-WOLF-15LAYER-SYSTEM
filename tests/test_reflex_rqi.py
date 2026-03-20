"""Unit tests for Reflex Quality Index (RQI) utility."""

from __future__ import annotations

import math

from analysis.reflex_rqi import compute_rqi, latency_decay


def test_latency_decay_is_one_at_zero_age() -> None:
    assert math.isclose(latency_decay(0.0, 60.0), 1.0, rel_tol=1e-9, abs_tol=1e-12)


def test_latency_decay_decreases_with_age() -> None:
    near = latency_decay(10.0, 60.0)
    far = latency_decay(60.0, 60.0)
    assert 0.0 <= far < near <= 1.0


def test_compute_rqi_matches_formula_components() -> None:
    rqi = compute_rqi(delta_t_sec=0.0, coherence=0.8, emotion_delta=0.2, sigma_sec=60.0)
    # dt=0 -> decay=1.0, so expected=0.8*(1-0.2)=0.64
    assert math.isclose(rqi, 0.64, rel_tol=1e-9, abs_tol=1e-12)


def test_compute_rqi_clamps_invalid_inputs() -> None:
    # coherence>1 and emotion_delta<0 should be clamped into [0,1].
    rqi = compute_rqi(delta_t_sec=-5.0, coherence=2.0, emotion_delta=-1.0, sigma_sec=0.0)
    assert 0.0 <= rqi <= 1.0
