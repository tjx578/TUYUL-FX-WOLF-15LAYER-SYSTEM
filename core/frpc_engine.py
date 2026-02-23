import numpy as np
from numpy import tanh


def calculate_frpc(
    fusion: float, trq: float, intensity: float,
    alpha: float, beta: float, gamma: float,
    integrity: float,
) -> float:
    # Standardize alpha, beta, gamma into [0,1]
    a, b, g = [np.clip(x, 0.0, 1.0) for x in [alpha, beta, gamma]]
    alpha_sync = np.clip((a + b + g) / 3, 0.0, 1.0)
    gamma_vals = [abs(a - b), abs(b - g), abs(a - g)]
    gamma_phase = np.mean(gamma_vals)
    raw = tanh(fusion) * tanh(trq) * tanh(intensity) * (alpha_sync / (1 + gamma_phase))
    integrity = np.clip(integrity, 0.0, 1.0)
    frpc_index = np.clip(raw * integrity, 0.0, 0.999)
    return frpc_index
