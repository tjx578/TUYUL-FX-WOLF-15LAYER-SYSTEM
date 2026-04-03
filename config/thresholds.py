from __future__ import annotations

from typing import Literal  # noqa: UP035

# Regime definitions
REGIME_TYPE = Literal["LOW_VOL", "NORMAL_VOL", "HIGH_VOL"]

THRESHOLD_TABLE: dict[str, dict[str, float]] = {
    "LOW_VOL": {
        "tii": 0.75,
        "frpc": 0.82,
        "integrity": 0.80,
        "mc_win": 0.55,
        "mc_pf": 1.3,
        "posterior": 0.58,
        "rr": 1.5,
        "risk_mult": 0.8,
        "conf12": 0.68,  # Tighter — data quality is higher in low-vol regimes
    },
    "NORMAL_VOL": {
        "tii": 0.70,
        "frpc": 0.78,
        "integrity": 0.78,
        "mc_win": 0.52,
        "mc_pf": 1.2,
        "posterior": 0.55,
        "rr": 1.5,
        "risk_mult": 1.0,
        "conf12": 0.65,  # Standard — balanced threshold for normal conditions
    },
    "HIGH_VOL": {
        "tii": 0.65,
        "frpc": 0.72,
        "integrity": 0.72,
        "mc_win": 0.48,
        "mc_pf": 1.1,
        "posterior": 0.50,
        "rr": 1.5,
        "risk_mult": 1.1,
        "conf12": 0.58,  # Relaxed — natural conf12 drop expected in high-vol regimes
    },
}


def get_thresholds(regime: REGIME_TYPE) -> dict[str, float]:
    return THRESHOLD_TABLE[regime]
