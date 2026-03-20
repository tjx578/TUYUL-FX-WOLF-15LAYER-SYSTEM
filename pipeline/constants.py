"""
Pipeline Constants v7.4r∞ - threshold accessors from config/constitution.yaml.

This module provides easy access to constitutional thresholds
for the Wolf 15-Layer Pipeline without hardcoding magic numbers.

9-Gate Constitutional Check thresholds:
    GATE 1: TIIₛᵧₘ ≥ 0.65
    GATE 2: Monte Carlo ≥ 50% (0.50 in config, multiplied by 100)
    GATE 3: FRPC State = SYNC
    GATE 4: CONF₁₂ ≥ 0.60
    GATE 5: RR ≥ 1:1.5
    GATE 6: Integrity ≥ 0.75
    GATE 7: PropFirm Compliant
    GATE 8: Drawdown ≤ 5.0%
    GATE 9: Latency ≤ 500ms
"""

from __future__ import annotations

from config.constitution import CONSTITUTION_THRESHOLDS


def get_tii_min() -> float:
    """Get TII minimum threshold (default: 0.65)."""
    return CONSTITUTION_THRESHOLDS.get("tii_min", 0.65)


def get_integrity_min() -> float:
    """Get integrity minimum threshold (default: 0.75)."""
    return CONSTITUTION_THRESHOLDS.get("integrity_min", 0.75)


def get_rr_min() -> float:
    """Get RR minimum threshold (default: 1.5)."""
    return CONSTITUTION_THRESHOLDS.get("rr_min", 1.5)


def get_fta_min() -> float:
    """Get FTA minimum threshold (default: 0.65)."""
    return CONSTITUTION_THRESHOLDS.get("fta_min", 0.65)


def get_monte_min() -> float:
    """Get Monte Carlo minimum threshold (default: 0.50)."""
    return CONSTITUTION_THRESHOLDS.get("monte_min", 0.50)


def get_conf12_min() -> float:
    """Get conf12 minimum threshold (default: 0.60)."""
    return CONSTITUTION_THRESHOLDS.get("conf12_min", 0.60)


def get_max_drawdown() -> float:
    """Get maximum drawdown threshold (default: 5.0)."""
    return CONSTITUTION_THRESHOLDS.get("max_drawdown", 5.0)


def get_max_latency_ms() -> float:
    """Get maximum latency threshold in milliseconds (default: 500)."""
    return CONSTITUTION_THRESHOLDS.get("max_latency_ms", 500)


def get_vault_sync_weights() -> dict[str, float]:
    """
    Get vault sync formula weights (3-component composite).

    Returns:
        dict with keys: feed, redis, integrity
        Default: feed=0.50, redis=0.30, integrity=0.20
    """
    vault_sync_config = CONSTITUTION_THRESHOLDS.get("vault_sync", {})
    formula_weights = vault_sync_config.get("formula_weights", {})

    return {
        "feed": formula_weights.get("feed", 0.50),
        "redis": formula_weights.get("redis", 0.30),
        "integrity": formula_weights.get("integrity", 0.20),
    }


def get_vault_sync_thresholds() -> dict[str, float]:
    """
    Get vault sync sovereignty thresholds.

    Returns:
        dict with keys: strict, operational, critical
        Default: strict=0.97, operational=0.90, critical=0.80
    """
    vault_sync_config = CONSTITUTION_THRESHOLDS.get("vault_sync", {})

    return {
        "strict": vault_sync_config.get("strict", 0.97),
        "operational": vault_sync_config.get("operational", 0.90),
        "critical": vault_sync_config.get("critical", 0.80),
    }


def get_meta_authority_weights() -> dict[str, float]:
    """
    Get meta authority computation weights.

    Returns:
        dict with keys: fusion_conf12, reflective_coherence, meta_integrity
    """
    meta_authority = CONSTITUTION_THRESHOLDS.get("meta_authority", {})
    weights = meta_authority.get("weights", {})

    return {
        "fusion_conf12": weights.get("fusion_conf12", 0.40),
        "reflective_coherence": weights.get("reflective_coherence", 0.30),
        "meta_integrity": weights.get("meta_integrity", 0.30),
    }
