"""WLWCI Calculator -- Weighted Layered Wave-Context Index."""

from datetime import UTC, datetime
from typing import Any, Final

from ._utils import _clamp, _clamp01

WLWCI_CONFIG: Final[dict[str, Any]] = {
    "version": "7.1.0",
    "weights": {"twms_macro": 0.42, "trend_fusion": 0.28, "twms_micro": 0.18, "volatility_penalty": 0.12},
    "micro_bounds": {
        "twms_micro_max": 0.30,
        "twms_micro_min": -0.30,
        "volatility_cap": 0.50,
        "min_confidence_multiplier": 0.70,
    },
    "volatility_regimes": {
        "low": {"threshold": 0.15, "confidence_boost": 1.05},
        "medium": {"threshold": 0.35, "confidence_boost": 1.00},
        "high": {"threshold": 0.55, "confidence_boost": 0.85},
        "extreme": {"threshold": 1.00, "confidence_boost": 0.70},
    },
    "orchestrator_thresholds": {"entry_min": 0.65, "strong_signal": 0.78, "exit_warning": 0.45, "emergency_exit": 0.30},
    "micro_rules": {
        "require_macro_alignment": True,
        "macro_alignment_threshold": 0.50,
        "disable_on_extreme_vol": True,
        "conflict_decay_factor": 0.50,
    },
    "fallback": {
        "no_micro_weights": {"twms_macro": 0.55, "trend_fusion": 0.45, "volatility_penalty": 0.00},
        "no_trend_weights": {"twms_macro": 0.70, "twms_micro": 0.30, "volatility_penalty": 0.15},
    },
}


def get_wlwci_config() -> dict[str, Any]:
    return WLWCI_CONFIG.copy()


def calculate_wlwci(
    twms_macro: float, trend_fusion: float, twms_micro: float, volatility: float, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    cfg = config or WLWCI_CONFIG
    w = cfg["weights"]
    b = cfg["micro_bounds"]
    r = cfg["volatility_regimes"]
    tmc = _clamp(twms_micro, b["twms_micro_min"], b["twms_micro_max"])
    vb, regime = 1.0, "medium"
    for rn, rc in r.items():
        if volatility <= rc["threshold"]:
            vb = rc["confidence_boost"]
            regime = rn
            break
    vp = min(volatility, b["volatility_cap"])
    raw = (
        w["twms_macro"] * twms_macro
        + w["trend_fusion"] * trend_fusion
        + w["twms_micro"] * tmc
        - w["volatility_penalty"] * vp
    )
    final = _clamp01(raw * vb)
    return {
        "wlwci": round(final, 4),
        "wlwci_raw": round(raw, 4),
        "volatility_regime": regime,
        "confidence_boost": vb,
        "components": {
            "twms_macro_contrib": round(w["twms_macro"] * twms_macro, 4),
            "trend_fusion_contrib": round(w["trend_fusion"] * trend_fusion, 4),
            "twms_micro_contrib": round(w["twms_micro"] * tmc, 4),
            "vol_penalty_contrib": round(w["volatility_penalty"] * vp, 4),
        },
        "timestamp": datetime.now(UTC).isoformat(),
    }
