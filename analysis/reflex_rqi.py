"""Reflex Quality Index (RQI) utilities.

RQI formula:
    RQI = exp(-(dt^2)/(2*sigma^2)) * C_sync * (1 - E_delta)

This module is analysis-only and has no execution side-effects.
"""

from __future__ import annotations

import math


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def latency_decay(delta_t_sec: float, sigma_sec: float) -> float:
    """Compute Gaussian latency decay term in [0, 1]."""
    dt = max(0.0, float(delta_t_sec))
    sigma = max(1e-9, float(sigma_sec))
    return math.exp(-((dt * dt) / (2.0 * sigma * sigma)))


def compute_rqi(
    delta_t_sec: float,
    coherence: float,
    emotion_delta: float,
    sigma_sec: float = 60.0,
) -> float:
    """Compute Reflex Quality Index (RQI) in [0, 1]."""
    decay = latency_decay(delta_t_sec, sigma_sec)
    c_sync = _clamp01(coherence)
    emotion_stability = 1.0 - _clamp01(emotion_delta)
    return _clamp01(decay * c_sync * emotion_stability)
