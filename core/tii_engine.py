
from numpy import tanh


def calculate_tii(
    trq: float,
    intensity: float,
    bias_strength: float,
    integrity: float,
    price: float,
    vwap: float,
    atr: float,
) -> float | None:
    if vwap == 0 or atr <= 0 or price <= 0:
        return None  # Invalid data
    deviation = abs(price - vwap) / atr
    raw_tii = (trq * intensity * bias_strength * integrity) / (1 + deviation)
    tii_index = tanh(raw_tii)
    return min(max(tii_index, 0.0), 0.999)
