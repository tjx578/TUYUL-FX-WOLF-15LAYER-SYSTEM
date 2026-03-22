from typing import Literal

RegimeType = Literal["LOW_VOL", "NORMAL_VOL", "HIGH_VOL"]


class RegimeDetectionError(Exception):
    pass


def calculate_atr_expansion_ratio(atr_current: float, atr_mean_20: float) -> float:
    if atr_mean_20 <= 0:
        raise RegimeDetectionError("ATR mean must be positive")
    return atr_current / atr_mean_20


def detect_volatility_regime(atr_ratio: float) -> RegimeType:
    if atr_ratio < 0.85:
        return "LOW_VOL"
    elif atr_ratio > 1.20:
        return "HIGH_VOL"
    else:
        return "NORMAL_VOL"
