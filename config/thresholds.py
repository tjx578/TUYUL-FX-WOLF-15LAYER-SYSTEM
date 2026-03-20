from typing import Literal  # noqa: UP035

# Regime definitions
REGIME_TYPE = Literal["LOW_VOL", "NORMAL_VOL", "HIGH_VOL"]

THRESHOLD_TABLE: dict[str, dict[str, float]] = {
    "LOW_VOL": {
        "tii": 0.93,
        "frpc": 0.96,
        "integrity": 0.97,
        "mc_win": 0.60,
        "mc_pf": 1.5,
        "posterior": 0.65,
        "rr": 2.0,
        "risk_mult": 0.8,
        "conf12": 0.78,
    },
    "NORMAL_VOL": {
        "tii": 0.90,
        "frpc": 0.93,
        "integrity": 0.95,
        "mc_win": 0.58,
        "mc_pf": 1.4,
        "posterior": 0.62,
        "rr": 2.0,
        "risk_mult": 1.0,
        "conf12": 0.72,
    },
    "HIGH_VOL": {
        "tii": 0.88,
        "frpc": 0.90,
        "integrity": 0.93,
        "mc_win": 0.55,
        "mc_pf": 1.5,
        "posterior": 0.60,
        "rr": 2.2,
        "risk_mult": 1.1,
        "conf12": 0.65,
    },
}


def get_thresholds(regime: REGIME_TYPE) -> dict[str, float]:
    return THRESHOLD_TABLE[regime]
