"""FRPC (Fusion Reflective Probability Coefficient) formula.

Zone: analysis/formulas/ — pure calculation, no side-effects.

Computes FRPC from fusion, TRQ, intensity, alpha/beta/gamma phase
synchronisation and integrity.  Consumed by constitution/layer12_pipeline.py.
"""

import numpy as np
from numpy import tanh

__all__ = ["calculate_frpc"]


def calculate_frpc(
    fusion: float,
    trq: float,
    intensity: float,
    alpha: float,
    beta: float,
    gamma: float,
    integrity: float,
) -> float:
    """Compute FRPC index in [0, 0.999]."""
    a, b, g = [np.clip(x, 0.0, 1.0) for x in [alpha, beta, gamma]]
    alpha_sync = np.clip((a + b + g) / 3, 0.0, 1.0)
    gamma_vals = [abs(a - b), abs(b - g), abs(a - g)]
    gamma_phase = np.mean(gamma_vals)
    raw = tanh(fusion) * tanh(trq) * tanh(intensity) * (alpha_sync / (1 + gamma_phase))
    integrity = np.clip(integrity, 0.0, 1.0)
    frpc_index = np.clip(raw * integrity, 0.0, 0.999)
    return frpc_index
